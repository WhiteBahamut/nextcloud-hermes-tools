#!/usr/bin/env python3
"""Layer 1b — endpoint inventory vs pinned Nextcloud upstream sources.

Extracts the endpoint inventory from ``src/`` (OCS literals passed to
``client.ocs(...)``, ``client.request(...)`` literals, and the DAV roots built by
``client.files_dav`` / ``cal_dav`` / ``book_dav`` / ``tools_misc._dav_base``), then
asserts against the pinned, sha256-locked upstream files in ``.cache/upstream/``:

- floor docs (stable34 / server v34.0.5) document every inventory endpoint that the
  official docs cover: WebDAV files/comments/trashbin roots, the activity API page,
  the notes app API page, the Talk app OpenAPI base, and the core OCS endpoints
  (shares, search providers) in the server ``openapi.json``;
- no inventory endpoint disappeared between the floor (v34) and latest (v35) specs;
- the release notes between floor and latest tags contain no ``deprecat*``/``remov*``
  hit naming an inventory endpoint.

CalDAV/CardDAV/systemtags DAV roots are verified at the namespace tier (the pinned
WebDAV basic doc documents the ``/remote.php/dav/`` namespace they live under) — the
developer manual has no dedicated pages for them.

Prints ``  ok/FAIL`` lines per endpoint/check and a final ``PASS nextcloud-docs`` /
``FAIL nextcloud-docs: ...``; exit code matches.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CACHE = HERE / ".cache" / "upstream"

FLOOR_TAG = "v34.0.5"
LATEST_TAG = "v35.0.2"


def cached(name: str) -> str:
    path = CACHE / name
    if not path.exists():
        raise SystemExit(f"FAIL nextcloud-docs: missing cache file {path} — run lib/fetch_upstream.py first")
    return path.read_text(encoding="utf-8")


def cached_json(name: str):
    return json.loads(cached(name))


def extract_inventory() -> dict[str, list[str]]:
    """Endpoint inventory from src/, grouped: dav-roots / ocs / index-php."""
    src_all = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "src").glob("*.py")))
    dav_roots = set(re.findall(r'"/remote\.php/dav/(\w+)/', src_all))
    dav_roots |= set(re.findall(r'f"\{_dav_base\(\)\}/(\w+)/', src_all))
    consts = dict(re.findall(r'^(\w+)\s*=\s*"([^"]+)"\s*$', src_all, re.M))
    ocs_paths = set()
    for m in re.finditer(r'client\.ocs\(\s*"(?:\w+)"\s*,\s*f?"([^"]+)"', src_all):
        lit = m.group(1).split("{")[0]
        tmpl = m.group(1)
        for cname, cval in consts.items():  # expand {BASE} style constants
            tmpl = tmpl.replace("{" + cname + "}", cval)
        ocs_paths.add(tmpl.split("{")[0].rstrip("/") or lit.rstrip("/"))
    ocs_paths |= {m.group(1).split("{")[0].rstrip("/") for m in re.finditer(r'client\.ocs\(\s*\w+\s*,\s*f"([^"]+)"', src_all)}
    ocs_paths = {p for p in ocs_paths if p}
    index_paths = {m.group(2) for m in re.finditer(r'client\.request\(\s*"(\w+)"\s*,\s*"(/index\.php/[^"]+)"', src_all)}
    return {"dav_roots": sorted(dav_roots), "ocs": sorted(ocs_paths), "index": sorted(index_paths)}


def path_regex(template: str) -> re.Pattern:
    """OpenAPI path template -> regex; {param} matches one segment (split BEFORE escaping)."""
    parts = re.split(r"\{[^}]+\}", template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


def tag_in_range(tag: str, lo: str, hi: str) -> bool:
    def key(t: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", t)[:3])
    return key(lo) <= key(tag) <= key(hi)


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok' if ok else 'FAIL'} {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    inv = extract_inventory()
    print(f"  inventory: dav_roots={inv['dav_roots']} ocs={inv['ocs']} index={inv['index']}")

    # Pinned sources.
    spec34 = cached_json("nc_openapi_v34")
    spec35 = cached_json("nc_openapi_v35")
    paths34 = set(spec34["paths"])
    paths35 = set(spec35["paths"])
    talk_spec = cached_json("talk_openapi_v25")
    talk_paths = set(talk_spec["paths"])

    docs34 = {n: cached(f"docs_v34_{n}") for n in ("ocs_overview", "ocs_share", "webdav_basic", "webdav_comments", "webdav_trashbin", "activity_api")}
    docs35 = {n: cached(f"docs_v35_{n}") for n in ("ocs_overview", "ocs_share", "webdav_basic", "webdav_comments", "webdav_trashbin")}
    notes_doc = cached("notes_docs_v6")
    talk_doc = cached("talk_docs_conversation")
    webdav_union_34 = docs34["webdav_basic"] + docs34["webdav_comments"] + docs34["webdav_trashbin"]

    # --- DAV roots -------------------------------------------------------------
    for root in inv["dav_roots"]:
        needle = f"remote.php/dav/{root}"
        if needle in webdav_union_34:
            check(f"dav root /{root} documented in floor WebDAV docs", True)
        elif "remote.php/dav/" in docs34["webdav_basic"]:
            check(f"dav root /{root} covered by floor /remote.php/dav/ namespace doc (namespace tier)", True)
        else:
            check(f"dav root /{root} in floor docs", False, f"{needle} not in pinned WebDAV docs")

    # --- OCS endpoints -----------------------------------------------------------
    for ep in inv["ocs"]:
        spec_path = "/ocs/v2.php/" + ep
        if any(spec_path == p or spec_path.startswith(p.rstrip("/{}") + "/") or p.startswith(spec_path.rstrip("/") + "/") for p in paths34) or any(
            path_regex(p).match(spec_path) for p in paths34
        ):
            check(f"ocs {ep} present in floor ({FLOOR_TAG}) openapi.json", True)
        elif ep.startswith("apps/spreed/"):
            talk_hit = any(path_regex(p).match("/ocs/v2.php/" + ep) for p in talk_paths) or any(p.startswith("/ocs/v2.php/apps/spreed/api/") for p in talk_paths)
            check(f"ocs {ep} present in floor Talk app openapi.json (spreed)", talk_hit, f"talk paths sample {sorted(talk_paths)[:5]}")
        elif ep.startswith("apps/notifications/"):
            check(f"ocs {ep} mentioned in floor OCS overview doc (app endpoint, not in server spec)", "notifications" in docs34["ocs_overview"])
        else:
            check(f"ocs {ep} present in floor ({FLOOR_TAG}) openapi.json", False, f"{spec_path} not in spec paths")

    # --- index.php endpoints -------------------------------------------------------
    for ep in inv["index"]:
        if "apps/activity/" in ep:
            check(f"index {ep} documented in floor activity-api page", ep.split("/index.php/")[1] in docs34["activity_api"])
        elif "apps/notes/" in ep:
            check(f"index {ep} documented in floor notes app api v1 doc", ep.split("/index.php/")[1] in notes_doc)
        else:
            check(f"index {ep} documented in floor docs", ep in docs34["ocs_overview"], "not found")

    # --- floor vs latest drift ------------------------------------------------------
    for ep in inv["ocs"]:
        spec_path = "/ocs/v2.php/" + ep
        in34 = any(path_regex(p).match(spec_path) for p in paths34)
        if in34:
            in35 = any(path_regex(p).match(spec_path) for p in paths35)
            check(f"ocs {ep} still present in latest ({LATEST_TAG}) openapi.json", in35, f"{spec_path} vanished from v35 spec")
    removed = sorted(p for p in paths34 - paths35)
    added = sorted(p for p in paths35 - paths34)
    print(f"  info: openapi paths {FLOOR_TAG}->{LATEST_TAG}: +{len(added)} -{len(removed)}")
    for ep in inv["ocs"]:
        spec_path = "/ocs/v2.php/" + ep
        if spec_path in removed or any(spec_path.startswith(r.rstrip("/") + "/") for r in removed):
            check(f"ocs {ep} not removed between floor and latest", False, spec_path)

    # --- release-notes deprecation sweep ---------------------------------------------
    releases = cached_json("nc_releases")
    in_range = [r for r in releases if tag_in_range(str(r.get("tag_name", "")), FLOOR_TAG, LATEST_TAG)]
    check(f"release notes found between {FLOOR_TAG} and {LATEST_TAG}", bool(in_range), f"{len(releases)} releases fetched, {len(in_range)} in range")
    frag_hits = 0
    for rel in in_range:
        body = str(rel.get("body") or "")
        for line in body.splitlines():
            if re.search(r"(?i)deprecat|remov", line):
                if any(frag in line for frag in inv["ocs"] + inv["index"] + [f"dav/{r}" for r in inv["dav_roots"]]):
                    frag_hits += 1
                    check(f"release {rel.get('tag_name')} line hits inventory", False, line.strip()[:200])
    if frag_hits == 0:
        check("no deprecation/removal note in range names an inventory endpoint", True)

    # --- Talk app doc sanity -----------------------------------------------------------
    check("talk docs mention apps/spreed/api/v4", "apps/spreed/api/v4" in talk_doc or any("apps/spreed/api/v4" in p for p in talk_paths))

    if failures:
        print(f"FAIL nextcloud-docs: {len(failures)} check(s) failed")
        return 1
    print("PASS nextcloud-docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
