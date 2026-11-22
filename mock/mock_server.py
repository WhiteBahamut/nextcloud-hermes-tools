"""Local mock of the Hermes dashboard host for the nextcloud-tools tab — NOT for production.

Serves, on one port (default http://127.0.0.1:8787/):
  GET /                                  -> mock/index.html (harness page)
  GET /mock-sdk.js                       -> mock SDK (mini-React + components)
  GET /dist/index.js, /dist/style.css    -> the REAL dashboard bundle, unmodified
  GET /manifest.json                     -> the real dashboard/manifest.json
  GET /api/plugins/nextcloud-tools/tools -> {"tools": [...]}   (same payload as plugin_api.py)
  PUT /api/plugins/nextcloud-tools/tools/{name}            body {"enabled": bool}
      -> {"ok": true, "disabled_tools": [...]}
  PUT /api/plugins/nextcloud-tools/tools/{name}/guardrails body {"enabled": bool}
      -> {"ok": true, "ungated_tools": [...]}
  Unknown tool name -> 400 {"detail": "unknown nc_* tool: ..."} (matches fastapi HTTPException).

Tool names, parameter docs and gate classes come from the real src/dashboard_store.py
(imported the same way dashboard/plugin_api.py imports it), so the mock renders exactly
what the host would. Toggle state lives in mock/state.json (git-ignored) and NEVER
touches ~/.hermes/config.yaml. Delete state.json to reset.

Stdlib only — no fastapi/hermes_cli needed. Run:
    python3 mock/mock_server.py [--host 127.0.0.1] [--port 8787]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

MOCK_ROOT = Path(__file__).resolve().parent
DASH_ROOT = MOCK_ROOT.parent / "dashboard"
PLUGIN_ROOT = DASH_ROOT.parent
STATE_FILE = MOCK_ROOT / "state.json"

# Load the plugin package the same way dashboard/plugin_api.py does, so the
# relative imports in dashboard_store (from . import schemas / .guardrails) resolve.
if "nextcloud_tools" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "nextcloud_tools",
        PLUGIN_ROOT / "src" / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT / "src")],
    )
    _pkg = importlib.util.module_from_spec(_spec)
    sys.modules["nextcloud_tools"] = _pkg
    _spec.loader.exec_module(_pkg)

from nextcloud_tools import dashboard_store  # noqa: E402

API_PREFIX = "/api/plugins/nextcloud-tools"
_PUT_RE = re.compile(r"^" + re.escape(API_PREFIX) + r"/tools/(nc_\w+)(/guardrails)?$")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

_lock = threading.Lock()


def _load_state() -> dict:
    """The persisted settings node {disabled_tools, ungated_tools}; {} when absent/corrupt."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _tools_payload() -> dict:
    """Same shape as plugin_api.list_tools: names/docs/gates live, toggles from state.json."""
    state = _load_state()
    disabled = set(dashboard_store.get_disabled_tools(_wrap(state)))
    ungated = set(dashboard_store.get_ungated_tools(_wrap(state)))
    return {
        "tools": [
            {
                "name": name,
                "gate": dashboard_store.classify_gate(name),
                "enabled": name not in disabled,
                "guarded": name not in ungated,
                **dashboard_store.tool_doc(name),
            }
            for name in dashboard_store.list_tool_names()
        ]
    }


def _wrap(settings: dict) -> dict:
    """Wrap the flat settings node in the config shape dashboard_store expects."""
    return {"plugins": {"entries": {"nextcloud-tools": {"settings": settings}}}}


def _unwrap(config: dict) -> dict:
    return config["plugins"]["entries"]["nextcloud-tools"]["settings"]


def _handle_put(name: str, guardrails: bool, body: dict) -> tuple[int, dict]:
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return 400, {"detail": "body must be {\"enabled\": bool}"}
    with _lock:
        config = _wrap(_load_state())
        try:
            if guardrails:
                result = dashboard_store.set_tool_guarded(config, name, enabled)
                key = "ungated_tools"
            else:
                result = dashboard_store.set_tool_enabled(config, name, enabled)
                key = "disabled_tools"
        except ValueError as exc:
            return 400, {"detail": str(exc)}
        _save_state(_unwrap(config))
    return 200, {"ok": True, key: result}


class MockHandler(BaseHTTPRequestHandler):
    server_version = "nc-tools-dashboard-mock/1.0"

    # -- helpers -----------------------------------------------------------
    def _send_json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            self._send_json(404, {"detail": "not found: " + self.path})
            return
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, root: Path, rel: str) -> None:
        """Serve root/rel with a path-traversal guard (resolved path must stay under root)."""
        candidate = (root / rel).resolve()
        if candidate != root.resolve() and root.resolve() not in candidate.parents:
            self._send_json(404, {"detail": "not found: " + self.path})
            return
        if not candidate.is_file():
            self._send_json(404, {"detail": "not found: " + self.path})
            return
        self._send_file(candidate)

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(MOCK_ROOT / "index.html")
        elif path == "/mock-sdk.js":
            self._send_file(MOCK_ROOT / "mock_sdk.js")
        elif path == "/manifest.json":
            self._send_file(DASH_ROOT / "manifest.json")
        elif path.startswith("/dist/"):
            self._static(DASH_ROOT, path.lstrip("/"))
        elif path == API_PREFIX + "/tools":
            with _lock:
                self._send_json(200, _tools_payload())
        else:
            self._send_json(404, {"detail": "not found: " + path})

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        m = _PUT_RE.match(path)
        if not m:
            self._send_json(404, {"detail": "not found: " + path})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except ValueError:
            self._send_json(400, {"detail": "invalid JSON body"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"detail": "invalid JSON body"})
            return
        code, obj = _handle_put(m.group(1), bool(m.group(2)), body)
        self._send_json(code, obj)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local mock host for the nextcloud-tools dashboard tab.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    server.daemon_threads = True
    print(f"mock dashboard: http://{args.host}:{args.port}/  (state: {STATE_FILE})")
    print("Ctrl-C to stop. Delete state.json to reset toggles.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
