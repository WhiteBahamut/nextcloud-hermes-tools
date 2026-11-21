"""Pin the generated TOOL_DOCS block in dashboard/dist/index.js to src/schemas.py.

The dashboard host mounts plugin API routes at process start and caches that
discovery per process, so a host started before plugin v0.24.0 still serves the
old GET /tools shape without ``parameters``. dist/index.js is served fresh and
therefore embeds a generated copy of every tool's doc payload
(dashboard/build_docs.py) as the fallback for the expanded doc panel. These
tests fail when the embedded block drifts from the live schemas.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "dashboard" / "dist" / "index.js"

# build_docs.py is stdlib-only (unlike dashboard/plugin_api.py, which is
# host-only and MUST NOT be imported here); load it by path, like conftest
# loads src/. When the test suite runs, conftest has already registered the
# nextcloud_tools package, so build_docs reuses it.
_spec = importlib.util.spec_from_file_location("nc_build_docs", ROOT / "dashboard" / "build_docs.py")
build_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_docs)

from nextcloud_tools import dashboard_store  # noqa: E402


def _embedded_stmt() -> str:
    """The ``var TOOL_DOCS = ...;`` statement between the sentinel comments."""
    src = INDEX_JS.read_text(encoding="utf-8")
    assert src.count(build_docs.BEGIN) == 1, "BEGIN sentinel must occur exactly once"
    assert src.count(build_docs.END) == 1, "END sentinel must occur exactly once"
    start = src.index(build_docs.BEGIN) + len(build_docs.BEGIN)
    end = src.index(build_docs.END)
    stmt = src[start:end].strip()
    assert stmt.startswith("var TOOL_DOCS = ") and stmt.endswith(";"), stmt[:80]
    return stmt


def test_generated_block_matches_live_schemas():
    """The embedded block is byte-identical to a fresh render (drift pin)."""
    src = INDEX_JS.read_text(encoding="utf-8")
    assert build_docs.splice(src, build_docs.render_block()) == src


def test_embedded_json_covers_every_manifest_tool_with_live_doc():
    stmt = _embedded_stmt()
    docs = json.loads(stmt[len("var TOOL_DOCS = ") : -1])
    names = dashboard_store.list_tool_names()
    assert set(docs) == set(names)
    assert len(docs) == 52  # guard against the sweep silently matching nothing
    for name in names:
        assert docs[name] == dashboard_store.tool_doc(name), name
        assert docs[name]["description"], name
        params = docs[name]["parameters"]
        assert isinstance(params, dict) and isinstance(params.get("properties"), dict), name


def test_check_mode_passes_and_writes_nothing():
    """--check exits 0 while in sync and never rewrites the bundle."""
    assert build_docs.main(["--check"]) == 0


def test_index_js_uses_the_fallback():
    src = INDEX_JS.read_text(encoding="utf-8")
    assert "function docFor(t)" in src
    assert "TOOL_DOCS[t.name]" in src
