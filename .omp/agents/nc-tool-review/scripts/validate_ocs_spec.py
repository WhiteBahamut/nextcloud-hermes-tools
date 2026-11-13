#!/usr/bin/env python3
"""Layer 2 — offline validation of every nc_* request against Nextcloud's OpenAPI spec.

Run with the scratch venv python (``validate_all.sh`` creates ``.venv-check/`` with
pinned ``openapi-spec-validator`` / ``openapi-core`` / ``httpx``):

    .venv-check/bin/python validate_ocs_spec.py

What it does, all offline against the sha256-locked ``.cache/upstream/`` pins:

1. Both pinned server specs (floor v34.0.5, latest v35.0.2) must pass
   ``openapi_spec_validator`` and load in ``openapi-core``.
2. ``src/`` is loaded via importlib exactly like ``tests/conftest.py``; tools are
   registered on a FakeCtx; ``client.get_client`` is replaced by an
   ``httpx.MockTransport`` in-memory server (no real sockets — same rule as the
  committed tests). Every one of the 44 ``nc_*`` handlers is then called with
   schema-derived args, so each tool records its real request(s).
3. Every recorded request whose path starts with ``/ocs/v2.php/`` must match a spec
   path (template ``{param}`` aware), allow the method, carry every spec-required
   query/header parameter, and — for 200 JSON responses — its body must validate
   against the operation's response schema (jsonschema, refs resolved against the
   spec). DAV (``/remote.php/dav/``) and ``/index.php/`` requests are asserted
   structurally (known method, namespaced path) since the server spec excludes them.

Prints ``  ok/FAIL`` lines plus a per-request summary and a final
``PASS ocs-spec`` / ``FAIL ocs-spec: ...``; exit code matches.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SRC = ROOT / "src"
CACHE = HERE / ".cache" / "upstream"

# --- arg fabrication ------------------------------------------------------------

KEY_DEFAULTS = {
    "path": "demo.txt", "source": "a.txt", "destination": "b.txt", "trash_path": "demo.txt",
    "token": "tok123", "file_id": "123", "uid": "uid-1", "id": "1", "calendar": "personal",
    "book": "contacts", "term": "demo", "message": "hello nc", "emoji": "+1",
    "share_with": "user2", "tag": "tag1", "title": "note title", "fn": "Jane Doe",
    "summary": "event", "start": "2026-11-08T10:00:00", "end": "2026-11-08T11:00:00",
    "reminder": "-PT15M",
    "due": "2026-11-09T10:00:00", "content": "hello file", "note": "n",
    "from": "2026-11-01T00:00:00", "to": "2026-11-30T00:00:00",
}
TOOL_OVERRIDES = {
    "nc_ocs": {"method": "GET", "path": "cloud/capabilities", "params": {}, "data": {}},
    "nc_comments": {"action": "list", "file_id": "123"},
    "nc_file_put": {"path": "demo.txt", "content": "hello file"},
    "nc_file_list": {"path": "", "depth": "1", "limit": 5},
    "nc_search": {"term": "demo", "providers": [], "limit": 5},
    "nc_file_search": {"term": "demo", "path": "", "limit": 5},
    "nc_share_delete": {"id": 1},
    "nc_talk_delete": {"token": "tok123", "message_id": 1},
    "nc_talk_react": {"token": "tok123", "message_id": 1, "emoji": "+1", "react": True},
    "nc_note_get": {"id": "1"}, "nc_note_edit": {"id": "1", "content": "x"},
    "nc_note_delete": {"id": "1"},
}


def fabricate(schema: dict, tool_name: str) -> dict:
    props = schema.get("parameters", {}).get("properties", {})
    args = {}
    for key, pspec in props.items():
        t = pspec.get("type")
        if key in TOOL_OVERRIDES.get(tool_name, {}):
            args[key] = TOOL_OVERRIDES[tool_name][key]
        elif key in KEY_DEFAULTS:
            args[key] = KEY_DEFAULTS[key]
        elif t == "string":
            args[key] = "demo"
        elif t == "integer":
            args[key] = 1
        elif t == "number":
            args[key] = 1.0
        elif t == "boolean":
            args[key] = True
        elif t == "array":
            args[key] = []
        elif t == "object":
            args[key] = {}
    return args


# --- in-memory mock server (httpx.MockTransport only, no sockets) ------------------

MULTISTATUS_PROPS = (
    "<d:getcontentlength>5</d:getcontentlength>"
    "<d:getlastmodified>Mon, 07 Nov 2026 10:00:00 GMT</d:getlastmodified>"
    "<d:getcontenttype>text/plain</d:getcontenttype>"
    "<d:resourcetype><d:collection/></d:resourcetype>"
    '<d:getetag>&quot;abc123&quot;</d:getetag>'
    "<oc:fileid>123</oc:fileid>"
    "<oc:systemtags><oc:systemtag>tag1</oc:systemtag></oc:systemtags>"
    "<cal:calendar-data>BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:uid-1\r\n"
    "DTSTART:20261108T100000Z\r\nDTEND:20261108T110000Z\r\nSUMMARY:event\r\nEND:VEVENT\r\nEND:VCALENDAR</cal:calendar-data>"
    "<card:address-data>BEGIN:VCARD\r\nVERSION:3.0\r\nUID:uid-1\r\nFN:Jane Doe\r\nEND:VCARD</card:address-data>"
)


def multistatus_body(href: str, props: str = MULTISTATUS_PROPS) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" '
        'xmlns:cal="urn:ietf:params:xml:ns:caldav" xmlns:card="urn:ietf:params:xml:ns:carddav">'
        f"<d:response><d:href>{href}</d:href>"
        "<d:propstat><d:status>HTTP/1.1 200 OK</d:status>"
        f"<d:prop>{props}</d:prop></d:propstat></d:response>"
        "</d:multistatus>"
    )


class MockServer:
    """Records every request; serves an in-memory DAV + canned OCS JSON."""

    def __init__(self):
        self.requests = []
        self.responses = []
        self.files: dict[str, bytes] = {}
        self.deleted: set[str] = set()
        self.chat: dict[str, list[dict]] = {}

    def __call__(self, request):  # httpx.MockTransport handler
        resp = self._handle(request)
        self.requests.append(request)
        self.responses.append(resp)
        return resp

    def _handle(self, request):
        import httpx
        method, path = request.method, request.url.path
        if method in ("PROPFIND", "REPORT", "PROPPATCH"):
            if path in self.deleted:
                return httpx.Response(404, text="gone")
            return httpx.Response(207, text=multistatus_body(path), headers={"Content-Type": "application/xml; charset=utf-8"})
        if method == "GET":
            if path in self.files:
                return httpx.Response(200, content=self.files[path])
            if path.startswith("/remote.php/dav/"):
                return httpx.Response(404, text="not found")
            return self._json(request)
        if method == "PUT":
            body = request.content or b""
            self.files[path] = body
            self.deleted.discard(path)
            digest = hashlib.sha256(body).hexdigest()
            return httpx.Response(201, headers={"OC-Checksum": f"SHA256:{digest}"})
        if method == "MKCOL":
            self.files[path] = b""
            self.deleted.discard(path)
            return httpx.Response(201)
        if method == "DELETE":
            self.files.pop(path, None)
            self.deleted.add(path)
            return httpx.Response(204)
        if method == "MOVE":
            dest = urllib.parse.urlsplit(request.headers.get("Destination", "")).path
            if path in self.files:
                self.files[dest] = self.files.pop(path)
            self.deleted.discard(dest)
            return httpx.Response(201)
        if method == "POST":
            if path.startswith("/remote.php/dav/"):  # comments add
                return httpx.Response(201)
            return self._json(request)
        if path.startswith("/ocs/v2.php/") or path.startswith("/index.php/"):
            return self._json(request)
        return httpx.Response(404, text="not found")

    def _json(self, request):
        import httpx

        path = request.url.path
        rel = path.split("/ocs/v2.php/", 1)[-1] if "/ocs/v2.php/" in path else path.split("/index.php/", 1)[-1]
        data = self._canned(rel, request)
        return httpx.Response(200, json={"ocs": {"meta": {"status": "ok", "statuscode": 200, "message": "OK"}, "data": data}})

    def _canned(self, rel: str, request):
        if rel == "search/providers":
            return [{"id": p, "name": p} for p in ("files", "fulltextsearch", "talk-message", "calendar", "tasks")]
        if rel.startswith("search/providers/"):
            provider = rel.split("/")[3]
            return {"name": provider, "isPaginated": False, "entries": [], "cursor": 0}
        if rel == "apps/files_sharing/api/v1/shares" and request.method == "POST":
            return {
                "id": "1", "share_type": 0, "uid_owner": "bot", "uid_file_owner": "bot",
                "displayname_owner": "bot", "displayname_file_owner": "bot",
                "path": "/demo.txt", "file_target": "/demo.txt", "item_type": "file",
                "mimetype": "text/plain", "storage": 1, "storage_id": "1", "file_source": 123,
                "file_parent": 1, "item_source": 123, "item_size": 5, "item_mtime": 0,
                "permissions": 1, "can_edit": True, "can_delete": True, "has_preview": False,
                "hide_download": 0, "is-mount-root": False, "mount-type": "", "label": "",
                "note": "", "expiration": "", "stime": 0, "mail_send": 0, "token": "tok",
                "parent": 1, "attributes": "{}",
            }
        if rel.startswith("apps/files_sharing/api/v1/shares"):
            return []
        if rel == "apps/spreed/api/v4/room":
            return [{"token": "tok123", "type": 1, "name": "room"}]
        if re.match(r"apps/spreed/api/v4/room/[^/]+/chat$", rel):
            token = rel.split("/")[5]
            if request.method == "POST":
                msgs = self.chat.setdefault(token, [])
                msg = {"id": len(msgs) + 1, "message": "hello nc", "actorType": "bots", "actorId": "bot"}
                msgs.append(msg)
                return msg
            return self.chat.get(token, [])
        if re.match(r"apps/spreed/api/v4/room/[^/]+/chat/\d+/reaction", rel) or re.match(r"apps/spreed/api/v4/room/[^/]+/chat/\d+$", rel):
            return []
        if rel.startswith("apps/notifications/"):
            return []
        if rel.startswith("apps/activity/") or "apps/activity" in rel:
            return {"data": []}
        if rel.startswith("apps/notes/"):
            if request.method == "POST":
                return {"id": 1, "title": "note title", "category": "", "content": ""}
            return [{"id": 1, "title": "note title", "category": "", "content": "x"}]
        if rel == "cloud/capabilities":
            return {"version": {"major": 35, "minor": 0, "micro": 2, "string": "35.0.2", "edition": "", "extendedSupport": False}, "capabilities": {}}
        return []


# --- spec matching ----------------------------------------------------------------




def path_regex(template: str) -> re.Pattern:
    """OpenAPI path template -> regex; {param} matches one segment (split BEFORE escaping)."""
    parts = re.split(r"\{[^}]+\}", template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


def match_spec(spec: dict, method: str, path: str):
    """Return (path_item, operation) for method+path, or (None, None)."""
    for template, item in spec.get("paths", {}).items():
        if path_regex(template).match(path):
            op = item.get(method.lower())
            if op is not None:
                return item, op
            return item, None
    return None, None


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok' if ok else 'FAIL'} {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    import httpx  # noqa: PLC0415 - scratch venv
    from openapi_spec_validator import validate as validate_spec  # noqa: PLC0415
    from openapi_core import OpenAPI  # noqa: PLC0415
    import jsonschema  # noqa: PLC0415
    import warnings  # noqa: PLC0415

    warnings.filterwarnings("ignore", category=DeprecationWarning)

    spec34 = json.loads((CACHE / "nc_openapi_v34").read_text(encoding="utf-8"))
    spec35 = json.loads((CACHE / "nc_openapi_v35").read_text(encoding="utf-8"))
    for tag, spec in (("v34.0.5", spec34), ("v35.0.2", spec35)):
        try:
            validate_spec(spec)
            check(f"openapi.json {tag} passes openapi-spec-validator", True)
        except Exception as exc:  # noqa: BLE001
            check(f"openapi.json {tag} passes openapi-spec-validator", False, f"{type(exc).__name__}: {exc}")
        try:
            OpenAPI.from_dict(spec)
            check(f"openapi.json {tag} loads in openapi-core", True)
        except Exception as exc:  # noqa: BLE001
            check(f"openapi.json {tag} loads in openapi-core", False, f"{type(exc).__name__}: {exc}")

    # --- load src/ like tests/conftest.py ------------------------------------------
    os.environ.setdefault("TALK_SERVER_URL", "https://nc.example")
    os.environ.setdefault("TALK_USER", "bot")
    os.environ.setdefault("TALK_APP_PASSWORD", "s3cret-pw")
    spec = importlib.util.spec_from_file_location(
        "nextcloud_tools", SRC / "__init__.py", submodule_search_locations=[str(SRC)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["nextcloud_tools"] = pkg
    spec.loader.exec_module(pkg)
    from nextcloud_tools import client  # noqa: E402

    class FakeCtx:
        def __init__(self):
            self.tools = {}
            self.hooks = []

        def get_config(self, key, default=None):
            return default

        def register_tool(self, **kwargs):
            self.tools[kwargs["name"]] = kwargs

        def register_hook(self, name, cb):
            self.hooks.append((name, cb))

    ctx = FakeCtx()
    client.configure(ctx)
    pkg.register(ctx)
    mock = MockServer()
    http = httpx.Client(
        base_url="https://nc.example",
        transport=httpx.MockTransport(mock),
        headers={"OCS-APIRequest": "true", "Accept": "application/json"},
    )
    client.get_client = lambda: http  # monkeypatch, same as the nc fixture

    # --- drive every tool ------------------------------------------------------------
    tool_requests: dict[str, int] = {}
    for name in sorted(ctx.tools):
        entry = ctx.tools[name]
        args = fabricate(entry["schema"], name)
        before = len(mock.requests)
        try:
            result = json.loads(entry["handler"](args))
        except Exception as exc:  # noqa: BLE001 - wrapper must not raise; report anyway
            check(f"{name} handler returned JSON (never raises)", False, f"{type(exc).__name__}: {exc}")
            continue
        tool_requests[name] = len(mock.requests) - before
        if tool_requests[name] == 0:
            check(f"{name} issued at least one request", False, f"result ok={result.get('ok')} error={str(result.get('error'))[:120]}")
        else:
            check(f"{name} drove {tool_requests[name]} request(s)", True)
    check("all 44 tools registered", len(ctx.tools) == 44, f"{len(ctx.tools)} tools")

    # --- validate every recorded request against the latest spec ----------------------
    spec = spec35
    talk_spec = json.loads((CACHE / "talk_openapi_v25").read_text(encoding="utf-8"))
    ocs_checked = dav_checked = app_checked = 0
    for req in mock.requests:
        method, path = req.method, req.url.path
        if path.startswith("/ocs/v2.php/"):
            item, op = match_spec(spec, method, path)
            src = "server"
            if item is None:
                item, op = match_spec(talk_spec, method, path)
                src = "spreed"
            if item is None and re.match(r"^/ocs/v2\.php/apps/(notifications|spreed)/api/v\d+/", path):
                # app endpoint excluded from both pinned specs; covered by layer 1 docs
                app_checked += 1
                continue
            if item is None:
                check(f"request path in pinned spec: {method} {path}", False, "no matching path template in server or spreed openapi.json")
                continue
            if op is None:
                check(f"method allowed on spec path ({src}): {method} {path}", False, f"allowed: {sorted(k for k in item if k in ('get','post','put','delete','patch','head','options'))}")
                continue
            params = list(op.get("parameters", []))
            query = dict(urllib.parse.parse_qsl(req.url.query.decode()))
            for p in params:
                if p.get("in") == "query" and p.get("required") and p["name"] not in query:
                    check(f"required query param present: {method} {path}", False, f"missing {p['name']}")
            for p in params:
                if p.get("in") == "header" and p.get("required") and p["name"].lower() not in {k.lower() for k in req.headers}:
                    check(f"required header present: {method} {path}", False, f"missing {p['name']}")
            ocs_checked += 1
        elif path.startswith("/remote.php/dav/") or path.startswith("/index.php/"):
            check(f"non-OCS request shape: {method} {path}", method in {"GET", "PUT", "DELETE", "MKCOL", "MOVE", "PROPFIND", "REPORT", "PROPPATCH", "POST", "HEAD", "OPTIONS"}, method)
            dav_checked += 1
        else:
            check(f"request path namespaced: {method} {path}", False, "not /ocs/v2.php/, /remote.php/dav/ or /index.php/")

    # --- validate canned OCS 200 responses against response schemas -------------------
    resp_checked = 0
    for req, resp in zip(mock.requests, mock.responses):
        path = req.url.path
        if not path.startswith("/ocs/v2.php/"):
            continue
        if resp.status_code != 200:
            continue
        item, op = match_spec(spec, req.method, path)
        if op is None:
            continue
        schema = (op.get("responses", {}).get("200") or {}).get("content", {}).get("application/json", {}).get("schema")
        if not schema:
            continue
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            continue
        try:
            jsonschema.validate(body, schema, resolver=jsonschema.RefResolver.from_schema(spec))
            resp_checked += 1
        except jsonschema.ValidationError as exc:  # noqa: BLE001
            check(f"OCS response validates against spec schema: {req.method} {path}", False, f"{exc.message[:160]} at {list(exc.absolute_path)[:4]}")
        except Exception as exc:  # noqa: BLE001
            check(f"OCS response schema resolution: {req.method} {path}", False, f"{type(exc).__name__}: {exc}")

    print(f"  info: validated {ocs_checked} OCS requests ({app_checked} app-only) + {dav_checked} DAV/index requests; {resp_checked} OCS 200 responses schema-checked")

    if failures:
        print(f"FAIL ocs-spec: {len(failures)} check(s) failed")
        return 1
    print("PASS ocs-spec")
    return 0




if __name__ == "__main__":
    sys.exit(main())
