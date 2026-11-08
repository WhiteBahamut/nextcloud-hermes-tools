#!/usr/bin/env python3
"""Layer 1a — static contract check of this plugin against the pinned Hermes loader source.

Reads the pinned upstream files from ``.cache/upstream/`` (run ``lib/fetch_upstream.py``
first) and asserts, stdlib-only:

1. ``"pre_tool_call"`` is a valid hook name in the pinned ``hermes_cli/hooks.py``
   (and referenced by the ``plugins.py`` facade).
2. ``PluginContext`` (pinned ``plugins_context.py``) defines ``register_tool``,
   ``register_hook`` and ``get_config``; every ``ctx.<method>`` used in ``src/`` is one
   of the pinned method names; the kwargs of the ``ctx.register_tool(...)`` call in
   ``src/__init__.py`` are all parameters of the pinned ``register_tool`` signature
   (unless it takes ``**kwargs``).
3. Every top-level key of ``plugin.yaml`` is a field of the pinned ``PluginManifest``
   model (``plugins_manifest.py``); ``version:`` is on line 2; ``provides_hooks`` names
   appear quoted in the pinned hooks source; ``provides_tools`` equals the union of the
   ``TOOLS`` names across ``src/tools_*.py``; the ``pre_tool_call`` hook is registered
   from ``src/__init__.py``.

Prints one ``  ok ...`` / ``  FAIL ...`` line per sub-check and a final
``PASS hermes-contract`` / ``FAIL hermes-contract: ...`` line; exit code matches.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # scripts/
ROOT = HERE.parents[3]  # repo root
CACHE = HERE / ".cache" / "upstream"

REQUIRED_CTX_METHODS = {"register_tool", "register_hook", "get_config"}
REGISTER_TOOL_KWARGS = {"name", "toolset", "schema", "handler", "check_fn", "requires_env", "description"}


def cached(name: str) -> str:
    path = CACHE / name
    if not path.exists():
        raise SystemExit(f"FAIL hermes-contract: missing cache file {path} — run lib/fetch_upstream.py first")
    return path.read_text(encoding="utf-8")


def class_body(source: str, class_name: str) -> str:
    m = re.search(rf"^class {class_name}\b.*?(?=^class |^@|\Z)", source, re.S | re.M)
    return m.group(0) if m else ""


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok' if ok else 'FAIL'} {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    hooks_src = cached("hermes_hooks_py")
    plugins_src = cached("hermes_plugins_py")
    context_src = cached("hermes_plugins_context_py")
    manifest_src = cached("hermes_plugins_manifest_py")

    # 1. pre_tool_call is a valid hook in the pinned loader.
    check('hooks source lists "pre_tool_call"', '"pre_tool_call"' in hooks_src)
    check("plugins.py facade references pre_tool_call", '"pre_tool_call"' in plugins_src)

    # 2. PluginContext surface.
    ctx_body = class_body(context_src, "PluginContext")
    check("PluginContext class found in pinned source", bool(ctx_body))
    ctx_methods = set(re.findall(r"def (\w+)\(", ctx_body)) if ctx_body else set()
    check(
        "PluginContext defines register_tool/register_hook/get_config",
        REQUIRED_CTX_METHODS <= ctx_methods,
        f"found {sorted(ctx_methods)[:12]}...",
    )
    m = re.search(r"def register_tool\(([^)]*)\)", ctx_body, re.S)
    if m:
        sig = m.group(1)
        raw_params = [p.strip() for p in sig.split(",") if p.strip()]
        raw_params = [p for p in raw_params if p != "self"]
        params = {p.split(":")[0].split("=")[0].lstrip("*") for p in raw_params}
        if any(p.startswith("**") for p in raw_params):
            check("register_tool accepts our kwargs (via **kwargs)", True)
        else:
            check(
                "register_tool kwargs used in src/__init__.py exist in pinned signature",
                REGISTER_TOOL_KWARGS <= params,
                f"missing {sorted(REGISTER_TOOL_KWARGS - params)}, signature params {sorted(params)}",
            )
    else:
        check("register_tool signature found in PluginContext", False, "no `def register_tool(...)` in class body")

    # Every ctx.<method> used in src/ must be a pinned PluginContext method.
    used: set[str] = set()
    for py in sorted((ROOT / "src").glob("*.py")):
        used |= set(re.findall(r"\bctx\.(\w+)", py.read_text(encoding="utf-8")))
    check(
        "all ctx.* methods used in src/ exist on pinned PluginContext",
        used <= ctx_methods,
        f"used {sorted(used)} but pinned PluginContext lacks {sorted(used - ctx_methods)}",
    )

    # 3. plugin.yaml vs pinned PluginManifest + TOOLS union + version line 2.
    manifest_body = class_body(manifest_src, "PluginManifest")
    check("PluginManifest class found in pinned source", bool(manifest_body))
    manifest_fields = set(re.findall(r"^\s{4}(\w+)\s*:", manifest_body, re.M)) if manifest_body else set()

    yaml_lines = (ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines()
    top_keys = {m.group(1) for line in yaml_lines if (m := re.match(r"^([a-z_]+):", line))}
    check(
        "plugin.yaml top-level keys are PluginManifest fields",
        top_keys <= manifest_fields,
        f"unknown keys {sorted(top_keys - manifest_fields)}; manifest fields {sorted(manifest_fields)}",
    )
    check("plugin.yaml line 2 is the version", bool(re.match(r"^version: \S+", yaml_lines[1] if len(yaml_lines) > 1 else "")), str(yaml_lines[1] if len(yaml_lines) > 1 else "<missing>"))

    def yaml_list(key: str) -> list[str]:
        out: list[str] = []
        in_block = False
        for line in yaml_lines:
            if re.match(rf"^{key}:", line):
                in_block = True
                continue
            if in_block:
                if re.match(r"^[a-z_]+:", line):
                    break
                m = re.match(r"^\s+-\s+(\S+)", line)
                if m:
                    out.append(m.group(1))
        return out

    provides_hooks = yaml_list("provides_hooks")
    check("provides_hooks non-empty", bool(provides_hooks), str(provides_hooks))
    check(
        "every provides_hooks name appears quoted in pinned hooks source",
        all(f'"{h}"' in hooks_src for h in provides_hooks),
        str(provides_hooks),
    )

    tools_union: set[str] = set()
    for py in sorted((ROOT / "src").glob("tools_*.py")):
        tools_union |= set(re.findall(r'\("(\w+)"\s*,\s*schemas\.', py.read_text(encoding="utf-8")))
    provides_tools = set(yaml_list("provides_tools"))
    check(
        "provides_tools == union of src/tools_*.py TOOLS names",
        provides_tools == tools_union,
        f"only in plugin.yaml: {sorted(provides_tools - tools_union)}; only in TOOLS: {sorted(tools_union - provides_tools)}",
    )

    init_src = (ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    check('src/__init__.py registers the pre_tool_call hook', 'register_hook("pre_tool_call"' in init_src)

    if failures:
        print(f"FAIL hermes-contract: {len(failures)} sub-check(s) failed")
        return 1
    print("PASS hermes-contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
