#!/usr/bin/env python3
"""Deterministic invariant runner for the dashboard-designer agent.

Read-only; stdlib only; no installs, no network. Run from anywhere:

    python3 .omp/agents/dashboard-designer/scripts/check_dashboard_bundle.py

Each check prints one ``  ok ...`` / ``  FAIL ...`` line plus a final
``PASS dashboard-bundle`` / ``FAIL dashboard-bundle: ...`` line; the exit code
matches. Checks over the shipped tab (``dashboard/`` + ``mock/`` + the contrast
guard in ``tests/``):

1. manifest: ``dashboard/manifest.json`` parses; ``name`` is non-empty; the
   ``entry`` and ``css`` files exist under ``dashboard/``.
2. register: ``dist/index.js`` calls ``__HERMES_PLUGINS__.register("<name>")``
   with the manifest ``name``.
3. ES5 bundle: with comments stripped, ``dist/index.js`` contains no arrow
   functions, no template literals, no ``const``/``let``, no ``import``/
   ``export`` statements (the bundle runs as-is in the browser, no build step).
4. no color literals: with comments stripped, ``dist/style.css`` contains no
   ``#rrggbb`` hex and no ``rgb()/rgba()/hsl()/hsla()`` — the plugin ships no
   color theme of its own, every color is a ``var(--color-*, var(--*))`` token.
5. font floor: every ``font-size`` in ``style.css`` is >= 0.75rem (or >= 12px).
6. a11y scaffolding: ``style.css`` defines ``:focus-visible`` rules and a
   ``prefers-reduced-motion`` block.
7. wire contract on all three sides: ``/api/plugins/nextcloud-tools`` + the
   ``/tools`` and ``/guardrails`` routes appear in ``dist/index.js``,
   ``dashboard/plugin_api.py`` (routes ``/tools/{name}`` and
   ``/tools/{name}/guardrails`` plus the mount path in the docstring),
   ``mock/mock_server.py``, and ``mock/README.md``.
8. SDK surface: every ``SDK.components.X`` / ``SDK.hooks.X`` / ``SDK.utils.X``
   / ``SDK.fetchJSON`` / ``SDK.React`` member used by ``dist/index.js`` is
   implemented by ``mock/mock_sdk.js`` (so the manual harness can render the
   real bundle).
9. classes: every ``nc-*`` class referenced in a string literal of
   ``dist/index.js`` has a matching selector in ``style.css`` (a trailing-dash
   literal like ``"nc-gate-"`` is a prefix: at least one ``.nc-gate-*``
   selector MUST exist).
10. contrast guard: ``tests/test_dashboard_contrast.py`` exists and reads
    ``dashboard/dist/style.css``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DASH = ROOT / "dashboard"
INDEX = DASH / "dist" / "index.js"
CSS = DASH / "dist" / "style.css"
MANIFEST = DASH / "manifest.json"
API = DASH / "plugin_api.py"
MOCK_SERVER = ROOT / "mock" / "mock_server.py"
MOCK_SDK = ROOT / "mock" / "mock_sdk.js"
MOCK_README = ROOT / "mock" / "README.md"
CONTRAST_TEST = ROOT / "tests" / "test_dashboard_contrast.py"

failures: list[str] = []


def ok(name: str) -> None:
    print(f"  ok {name}")


def fail(name: str, detail: str) -> None:
    failures.append(name)
    print(f"  FAIL {name}: {detail}")


def strip_js_comments(code: str) -> str:
    """Remove // and /* */ comments, preserving string literals."""
    out: list[str] = []
    i, n = 0, len(code)
    quote = ""
    while i < n:
        c = code[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_js_strings(code: str) -> str:
    """Blank out string-literal contents so lint regexes cannot match inside them."""
    out: list[str] = []
    i, n = 0, len(code)
    quote = ""
    while i < n:
        c = code[i]
        if quote:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = ""
                out.append(c)
            i += 1
            continue
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def check_manifest() -> str | None:
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report any parse failure
        fail("manifest parses", str(exc))
        return None
    name = m.get("name")
    if not name or not isinstance(name, str):
        fail("manifest name", f"missing/empty name: {name!r}")
        return None
    for key in ("entry", "css"):
        rel = m.get(key)
        if not rel or not (DASH / rel).is_file():
            fail(f"manifest {key}", f"{rel!r} does not exist under dashboard/")
    if not failures:
        ok("manifest parses; name + entry + css present")
    return name


def check_register(name: str) -> None:
    code = INDEX.read_text(encoding="utf-8")
    m = re.search(r"__HERMES_PLUGINS__\.register\(\s*[\"']([^\"']+)[\"']", code)
    if m and m.group(1) == name:
        ok(f"register name matches manifest ({name})")
    else:
        fail("register name", f"register({m.group(1) if m else None!r}) != manifest name {name!r}")


def check_es5() -> None:
    code = strip_js_strings(strip_js_comments(INDEX.read_text(encoding="utf-8")))
    bad = []
    if "=>" in code:
        bad.append("arrow function")
    if "`" in code:
        bad.append("template literal")
    for pat, label in ((r"\bconst\b", "const"), (r"\blet\b", "let"),
                       (r"(?m)^\s*import\b", "import statement"), (r"(?m)^\s*export\b", "export statement")):
        if re.search(pat, code):
            bad.append(label)
    if bad:
        fail("ES5 bundle", "found: " + ", ".join(bad))
    else:
        ok("ES5 bundle (no arrows/templates/const/let/import/export)")


def check_no_color_literals() -> None:
    css = strip_css_comments(CSS.read_text(encoding="utf-8"))
    hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", css) + re.findall(r"\b(?:rgba?|hsla?)\s*\(", css)
    if hits:
        fail("no color literals", f"found {hits[:5]} in style.css")
    else:
        ok("no hex/rgb/hsl literals in style.css")


def check_font_floor() -> None:
    css = strip_css_comments(CSS.read_text(encoding="utf-8"))
    bad = []
    for value, unit in re.findall(r"font-size:\s*([\d.]+)\s*(rem|px|em)\b", css):
        v = float(value)
        if unit == "rem" and v < 0.75 - 1e-9:
            bad.append(f"{value}rem")
        elif unit == "px" and v < 12 - 1e-9:
            bad.append(f"{value}px")
        elif unit == "em" and v < 0.75 - 1e-9:
            bad.append(f"{value}em")
    if bad:
        fail("font floor 0.75rem", "below floor: " + ", ".join(bad))
    else:
        ok("font floor (all font-size >= 0.75rem / 12px)")


def check_a11y_scaffolding() -> None:
    css = strip_css_comments(CSS.read_text(encoding="utf-8"))
    missing = []
    if ":focus-visible" not in css:
        missing.append(":focus-visible rules")
    if "prefers-reduced-motion" not in css:
        missing.append("prefers-reduced-motion block")
    if missing:
        fail("a11y scaffolding", "missing " + " + ".join(missing))
    else:
        ok(":focus-visible rules + prefers-reduced-motion present")


def check_wire_contract() -> None:
    index = INDEX.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    mock = MOCK_SERVER.read_text(encoding="utf-8")
    readme = MOCK_README.read_text(encoding="utf-8")
    problems = []
    if "/api/plugins/nextcloud-tools" not in index:
        problems.append("index.js missing /api/plugins/nextcloud-tools")
    if "/guardrails" not in index or "/tools/" not in index:
        problems.append("index.js missing /tools/ or /guardrails")
    if "/api/plugins/nextcloud-tools" not in api:
        problems.append("plugin_api.py missing mount path in docstring")
    if '"/tools/{name}"' not in api or '"/tools/{name}/guardrails"' not in api:
        problems.append("plugin_api.py missing PUT route decorators")
    if '"/api/plugins/nextcloud-tools"' not in mock or "/guardrails" not in mock:
        problems.append("mock_server.py missing API prefix or /guardrails")
    if "/tools/{name}" not in readme or "/tools/{name}/guardrails" not in readme:
        problems.append("mock/README.md missing PUT routes")
    if problems:
        fail("wire contract", "; ".join(problems))
    else:
        ok("wire contract strings present in index.js, plugin_api.py, mock_server.py, README")


def _object_keys(source: str, obj_name: str) -> set[str]:
    """Keys of a ``name: { ... }`` object literal, via simple brace matching."""
    m = re.search(re.escape(obj_name) + r":\s*\{", source)
    if not m:
        return set()
    depth = 0
    i = m.end() - 1
    start = i
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = source[start + 1 : i]
    return set(re.findall(r"(\w+)\s*:", body))


def check_sdk_surface() -> None:
    index = INDEX.read_text(encoding="utf-8")
    sdk = MOCK_SDK.read_text(encoding="utf-8")
    used_components = set(re.findall(r"SDK\.components\.(\w+)", index))
    used_hooks = set(re.findall(r"SDK\.hooks\.(\w+)", index))
    used_utils = set(re.findall(r"SDK\.utils\.(\w+)", index))
    missing = []
    mock_components = _object_keys(sdk, "components")
    mock_hooks = _object_keys(sdk, "hooks")
    mock_utils = _object_keys(sdk, "utils")
    for c in sorted(used_components - mock_components):
        missing.append(f"components.{c}")
    for h in sorted(used_hooks - mock_hooks):
        missing.append(f"hooks.{h}")
    for u in sorted(used_utils - mock_utils):
        missing.append(f"utils.{u}")
    if "SDK.fetchJSON" in index and not re.search(r"fetchJSON\s*:\s*\w+", sdk):
        missing.append("fetchJSON")
    if "SDK.React" in index and "createElement" not in sdk:
        missing.append("React.createElement")
    if missing:
        fail("SDK surface covered by mock", "not in mock_sdk.js: " + ", ".join(missing))
    else:
        ok(f"SDK surface covered by mock ({len(used_components)} components, {len(used_hooks)} hooks)")


# String literals that look like nc-* tokens but are NOT css classes.
NON_CLASS_STRINGS = {"nc-tools-expanded-v1"}  # localStorage key for expanded rows
# Classes intentionally without a style.css rule (block container only — the
# "required" pill .nc-req has its own rule). Re-review when the bundle changes.
LAYOUT_ONLY_CLASSES = {"nc-group"}


def check_classes() -> None:
    index = INDEX.read_text(encoding="utf-8")
    css = strip_css_comments(CSS.read_text(encoding="utf-8"))
    literals = re.findall(r'"([^"\n]*)"', index) + re.findall(r"'([^'\n]*)'", index)
    classes: set[str] = set()
    for lit in literals:
        if lit in NON_CLASS_STRINGS:
            continue
        classes.update(re.findall(r"\bnc-[a-z0-9-]+", lit))
    classes -= LAYOUT_ONLY_CLASSES
    missing = []
    for cls in sorted(classes):
        if cls.endswith("-"):  # prefix composition, e.g. "nc-gate-" + tone
            if not re.search(r"\." + re.escape(cls) + r"[a-z0-9-]", css):
                missing.append(cls + "<tone>")
        elif not re.search(r"\." + re.escape(cls) + r"(?![a-z0-9-])", css):
            missing.append(cls)
    if missing:
        fail("nc-* classes defined in style.css", "no selector for: " + ", ".join(missing))
    else:
        ok(f"all {len(classes)} nc-* classes used in index.js have CSS selectors")


def check_contrast_guard() -> None:
    if CONTRAST_TEST.is_file() and "style.css" in CONTRAST_TEST.read_text(encoding="utf-8"):
        ok("contrast guard tests/test_dashboard_contrast.py reads style.css")
    else:
        fail("contrast guard", "tests/test_dashboard_contrast.py missing or not reading style.css")


def main() -> int:
    name = check_manifest()
    if name:
        check_register(name)
    check_es5()
    check_no_color_literals()
    check_font_floor()
    check_a11y_scaffolding()
    check_wire_contract()
    check_sdk_surface()
    check_classes()
    check_contrast_guard()
    if failures:
        print(f"FAIL dashboard-bundle: {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("PASS dashboard-bundle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
