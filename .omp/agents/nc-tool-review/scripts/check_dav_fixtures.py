#!/usr/bin/env python3
"""Layer 3 — parse upstream multistatus/XML fixtures with the plugin's own parsers.

Fixture sources (pinned, sha256-locked in ``.cache/upstream/``):

- RFC 4918 (WebDAV) text — its multistatus examples exercise per-propstat
  ``HTTP/1.1 200/403/412`` status lines;
- the XML examples embedded in the pinned Nextcloud developer-manual ``.rst``
  pages (floor stable34 + latest stable35): the comments multistatus and the
  PROPFIND/PROPPATCH/REPORT request bodies from WebDAV basic.

Every extracted ``<multistatus>`` block is parsed with ``src/dav.py`` (loaded via
importlib exactly like ``tests/conftest.py``) and must parse without exception and
yield one entry per ``<response>`` (href present whenever the block has hrefs).
Every XML code-block from the docs must be well-formed XML. The load-bearing
Nextcloud quirk — HTML-escaped etags (``&quot;``) in multistatus, unescaped before
``If-Match`` (``src/tools_cal.py``) — is asserted on a synthetic 207 body with
propstat 200 + 404 (labeled synthetic; the RFC/docs examples do not carry it):
``ElementTree`` must deliver the etag with real quotes. ``dav.PROPFIND_ALL`` must
stay well-formed.

Prints ``  ok/FAIL`` lines and a final ``PASS dav-fixtures`` / ``FAIL dav-fixtures: ...``;
exit code matches.
"""

from __future__ import annotations

import html
import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SRC = ROOT / "src"
CACHE = HERE / ".cache" / "upstream"

MS_RE = re.compile(r"<(?:\w+:)?multistatus\b[\s\S]*?</(?:\w+:)?multistatus\s*>", re.I)
STATUS_RE = re.compile(r"HTTP/1\.1\s+(\d{3})")
CODE_BLOCK_RE = re.compile(r"^\s*\.\. code-block::\s*(\w+)\s*$", re.I)

DOC_SOURCES = [
    "docs_v34_webdav_basic", "docs_v34_webdav_comments", "docs_v34_webdav_trashbin",
    "docs_v34_ocs_overview", "docs_v34_ocs_share", "docs_v34_activity_api",
    "docs_v35_webdav_basic", "docs_v35_webdav_comments", "docs_v35_webdav_trashbin",
    "docs_v35_ocs_overview", "docs_v35_ocs_share",
]


def cached(name: str) -> str:
    path = CACHE / name
    if not path.exists():
        raise SystemExit(f"FAIL dav-fixtures: missing cache file {path} — run lib/fetch_upstream.py first")
    return path.read_text(encoding="utf-8")


def load_dav():
    spec = importlib.util.spec_from_file_location("nextcloud_tools_dav_under_test", SRC / "dav.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_rfc(text: str) -> str:
    """Strip RFC page-break artifacts (form feeds, [Page N] markers, running headers)."""
    text = text.replace("\f", "")
    text = re.sub(r"^\[Page \d+\]\s*$", "", text, flags=re.M)
    text = re.sub(r"^RFC 4918\s+.*$", "", text, flags=re.M)
    return text


def rst_xml_blocks(text: str) -> list[str]:
    """XML payloads of ``.. code-block:: xml`` directives, sliced at the first '<'."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        m = CODE_BLOCK_RE.match(lines[i])
        if m and m.group(1).lower() == "xml":
            j = i + 1
            block = []
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                block.append(lines[j])
                j += 1
            body = "\n".join(block)
            cut = re.search(r"<\?xml|<(?:\w+:)?[A-Za-z]", body)
            if cut:
                out.append(body[cut.start():])
            i = j
        else:
            i += 1
    return out

def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok' if ok else 'FAIL'} {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    dav = load_dav()
    sources = {name: cached(name) for name in DOC_SOURCES}
    sources["rfc4918_webdav"] = clean_rfc(cached("rfc4918_webdav"))

    total_blocks = 0
    total_responses = 0
    statuses: set[str] = set()
    for src_name, text in sources.items():
        for block in MS_RE.findall(text):
            total_blocks += 1
            statuses |= set(STATUS_RE.findall(block))
            has_href = "<href" in block.lower()
            try:
                parsed = dav.parse_multistatus(block)
            except Exception as exc:  # noqa: BLE001
                check(f"multistatus block from {src_name} parses", False, f"{type(exc).__name__}: {exc}")
                continue
            n_resp = len(re.findall(r"<(?:\w+:)?response\b", block, re.I))
            if len(parsed) != n_resp:
                check(f"multistatus block from {src_name} yields one entry per response", False, f"{len(parsed)} != {n_resp}")
                continue
            if has_href and any(not r.get("href") for r in parsed):
                check(f"multistatus block from {src_name} keeps hrefs", False, "empty href after parse")
                continue
            total_responses += len(parsed)

    check("found multistatus fixtures in pinned sources", total_blocks >= 8, f"only {total_blocks} blocks")
    check("all upstream multistatus fixtures parse (one entry per response)", total_blocks > 0 and total_responses >= total_blocks, f"{total_blocks} blocks, {total_responses} responses")
    check("fixtures exercise per-propstat status lines incl. 200 and a 4xx", "200" in statuses and any(s.startswith("4") for s in statuses), f"statuses: {sorted(statuses)}")

    # XML code-blocks from the docs must be well-formed.
    xml_blocks = 0
    for src_name in DOC_SOURCES:
        for block in rst_xml_blocks(sources[src_name]):
            if "<" not in block:
                continue
            xml_blocks += 1
            try:
                ET.fromstring(block)
            except Exception as exc:  # noqa: BLE001
                check(f"xml code-block from {src_name} well-formed", False, f"{type(exc).__name__}: {exc}")
    check("doc XML code-blocks are well-formed", xml_blocks >= 4, f"{xml_blocks} blocks")

    # Synthetic quirk fixture (documented Nextcloud behavior, not from the RFC):
    # 207 multistatus, propstat 200 with HTML-escaped etag + propstat 404.
    quirk = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
        "<d:response><d:href>/remote.php/dav/files/bot/demo.txt</d:href>"
        "<d:propstat><d:status>HTTP/1.1 200 OK</d:status>"
        '<d:prop><d:getetag>&quot;abc123&quot;</d:getetag><oc:fileid>123</oc:fileid></d:prop></d:propstat>'
        "<d:propstat><d:status>HTTP/1.1 404 Not Found</d:status>"
        "<d:prop><d:resourcetype/></d:prop></d:propstat>"
        "</d:response></d:multistatus>"
    )
    try:
        parsed = dav.parse_multistatus(quirk)
        etag = parsed[0]["props"].get("getetag")
        check(
            "synthetic 207 quirk fixture: escaped etag unescapes, 404 propstat tolerated",
            parsed and etag == '"abc123"' and html.unescape(etag) == etag,
            f"etag={etag!r}",
        )
    except Exception as exc:  # noqa: BLE001
        check("synthetic 207 quirk fixture parses", False, f"{type(exc).__name__}: {exc}")

    try:
        ET.fromstring(dav.PROPFIND_ALL)
        check("dav.PROPFIND_ALL is well-formed XML", True)
    except Exception as exc:  # noqa: BLE001
        check("dav.PROPFIND_ALL is well-formed XML", False, str(exc))

    print(f"  info: parsed {total_blocks} upstream multistatus blocks / {total_responses} responses + {xml_blocks} doc XML blocks from {len(sources)} pinned sources")
    if failures:
        print(f"FAIL dav-fixtures: {len(failures)} check(s) failed")
        return 1
    print("PASS dav-fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
