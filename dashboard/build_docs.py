#!/usr/bin/env python3
"""Regenerate the embedded TOOL_DOCS block in ``dashboard/dist/index.js``.

The dashboard host mounts a plugin's API routes at process start and caches that
discovery per process, so a host started before plugin v0.24.0 keeps serving the
old ``GET /tools`` shape without ``parameters``. The static bundle
(``dist/index.js``) is served fresh, so it carries a generated copy of every
tool's doc payload as a fallback; ``index.js`` prefers the live API payload when
it carries ``parameters``.

Stdlib only — safe to import from the test suite (unlike ``plugin_api.py``,
which is host-only). Run from the repo root:

    python3 dashboard/build_docs.py          # rewrite the block in dist/index.js
    python3 dashboard/build_docs.py --check  # exit 1 if the block is stale
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = DASHBOARD_DIR.parent
INDEX_JS = DASHBOARD_DIR / "dist" / "index.js"

BEGIN = "// BEGIN GENERATED TOOL DOCS (dashboard/build_docs.py)"
END = "// END GENERATED TOOL DOCS"

# Load src/ as the nextcloud_tools package, same guard as plugin_api.py / conftest.py.
if "nextcloud_tools" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "nextcloud_tools",
        PLUGIN_ROOT / "src" / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT / "src")],
    )
    _pkg = importlib.util.module_from_spec(_spec)
    sys.modules["nextcloud_tools"] = _pkg
    _spec.loader.exec_module(_pkg)


def build_docs() -> dict[str, dict]:
    """Map every manifest tool name to its live doc payload (description + parameters)."""
    from nextcloud_tools import dashboard_store

    return {name: dashboard_store.tool_doc(name) for name in dashboard_store.list_tool_names()}


def render_block() -> str:
    """The full sentinel-delimited JS block, ready to splice into dist/index.js."""
    body = json.dumps(build_docs(), indent=1, ensure_ascii=False, sort_keys=True)
    return f"{BEGIN}\nvar TOOL_DOCS = {body};\n{END}"


def splice(index_src: str, block: str) -> str:
    """Replace the sentinel-delimited block in ``index_src``.

    Raises SystemExit unless exactly one BEGIN/END sentinel pair is present, so a
    mangled file is never rewritten blindly.
    """
    if index_src.count(BEGIN) != 1 or index_src.count(END) != 1:
        raise SystemExit(
            f"expected exactly one sentinel pair in {INDEX_JS}, "
            f"found {index_src.count(BEGIN)}/{index_src.count(END)}"
        )
    start = index_src.index(BEGIN)
    end = index_src.index(END) + len(END)
    return index_src[:start] + block + index_src[end:]


def main(argv: list[str]) -> int:
    """Rewrite the TOOL_DOCS block in place, or only check it with ``--check``."""
    check = "--check" in argv
    current = INDEX_JS.read_text(encoding="utf-8")
    updated = splice(current, render_block())
    if updated == current:
        print(f"TOOL_DOCS block in {INDEX_JS} is up to date ({len(build_docs())} tools)")
        return 0
    if check:
        print(f"FAIL: TOOL_DOCS block in {INDEX_JS} is stale — run `python3 dashboard/build_docs.py`")
        return 1
    INDEX_JS.write_text(updated, encoding="utf-8")
    print(f"wrote TOOL_DOCS block ({len(build_docs())} tools) into {INDEX_JS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
