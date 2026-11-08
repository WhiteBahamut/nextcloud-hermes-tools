#!/usr/bin/env python3
"""Deterministic runner for the nc-security-review grep checklist.

Read-only; stdlib only; no installs. Scope: files changed in the working tree
(``git status --porcelain``) plus the last three commits (``git diff --name-only
HEAD~3..HEAD``), filtered to the audit scope ``src/``, ``tests/``, ``plugin.yaml``,
``dashboard/``, ``AGENTS.md``.

Checks (each printed as ``  ok ...`` / ``  FAIL ...``; final line
``PASS security-invariants`` / ``FAIL security-invariants: ...``; exit code matches):

1. secrets: no secret-value assignment (``password|secret|app_password|token`` =
   literal) in scoped changed files (test fake values allowlisted); no ``os.getenv``
   for secrets outside ``src/client.py``; the word-grep from the checklist is counted
   as an info line, not a failure.
2. URLs: no ``https?://`` literal outside ``src/client.py``, except XML namespace URIs
   (``owncloud.org/ns``, ``urn:ietf:``) in src and the mock hosts ``nc.example`` /
   ``talk.example`` in tests.
3. request paths: every ``client.request/ocs/propfind/dav_*`` call site in changed
   ``src/tools_*.py`` must not interpolate raw ``args`` into the path (paths go
   through ``enc_path`` + ``files_dav``/``cal_dav``/``book_dav``/``_dav_base``);
   ``src/client.py`` still rejects ``..`` traversal; ``tools_misc._ocs`` still rejects
   leading ``/`` and ``..`` before any request.
4. read-back: every WRITES/DESTRUCTIVE tool (parsed from ``src/guardrails.py`` via
   ast) has a handler whose source mentions verification (``verif``); ``nc_ocs`` is
   the documented arg-dispatch escape hatch and is exempt.
5. wiring: every tool in the ``TOOLS`` lists has a schema in ``src/schemas.py``, an
   entry in ``plugin.yaml`` ``provides_tools``, and a guardrails classification.
6. tests stay hermetic: changed ``tests/*.py`` use ``httpx.MockTransport`` and contain
   no real sockets/HTTP clients/URLs beyond the mock hosts.
7. deps: ``plugin.yaml`` ``python_dependencies`` stays ``[httpx]``; imports in changed
   ``src/*.py`` are stdlib, ``httpx``, the host ``agent`` package, or relative.
8. gating: ``src/__init__.py`` registers the ``pre_tool_call`` hook and
   ``src/guardrails.py`` defines ``guard``.

With no scoped changes it prints ``PASS security-invariants (no scoped changes)``.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCOPE = ("src/", "tests/", "plugin.yaml", "dashboard/", "AGENTS.md")
FAKE_SECRET_VALUES = {"s3cret-pw", "nc-pw", "talkpw", "pw", "pw-one", "test", "dummy", "fake", "xxx", "changeme"}
SECRET_ASSIGN_RE = re.compile(r"(?i)\b(password|secret|app_password|token)\b\s*[:=]\s*[\"']([^\"']{3,})[\"']")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
WORD_RE = re.compile(r"(?i)password|secret|token|app_password|Authorization")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False).stdout


def changed_files() -> list[str]:
    files: set[str] = set()
    for line in git("status", "--porcelain").splitlines():
        path = line[3:].strip()
        if path:
            files.add(path)
    probe = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD~3"], capture_output=True)
    if probe.returncode == 0:
        files |= set(git("diff", "--name-only", "HEAD~3..HEAD").split())
    return sorted(f for f in files if f.startswith(SCOPE) and (ROOT / f).exists())


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok' if ok else 'FAIL'} {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    files = changed_files()
    if not files:
        print("PASS security-invariants (no scoped changes detected)")
        return 0
    print(f"  scoped changed files: {', '.join(files)}")

    texts = {f: (ROOT / f).read_text(encoding="utf-8", errors="replace") for f in files}

    # 1. secrets
    for f, text in texts.items():
        for i, line in enumerate(text.splitlines(), 1):
            m = SECRET_ASSIGN_RE.search(line)
            if m and m.group(2) not in FAKE_SECRET_VALUES:
                check(f"no secret-value literal in {f}", False, f"line {i}: {line.strip()[:120]}")
    check("no secret-value literals in scoped changed files", all("secret-value" not in x for x in failures))
    for f, text in texts.items():
        if f.startswith("src/") and f != "src/client.py":
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"os\.getenv\(", line):
                    check(f"no os.getenv in {f}", False, f"line {i}: {line.strip()[:120]}")
    check("no os.getenv for secrets outside src/client.py", all("os.getenv" not in x for x in failures))
    word_count = sum(len(WORD_RE.findall(t)) for t in texts.values())
    print(f"  info: checklist word-grep (password|secret|token|app_password|Authorization) hits in scoped files: {word_count} (reviewed, not auto-fail)")

    # 2. URL literals
    bad_urls = []
    for f, text in texts.items():
        for i, line in enumerate(text.splitlines(), 1):
            for m in URL_RE.finditer(line):
                url = m.group(0)
                if f == "src/client.py":
                    continue
                if f.startswith("tests/") and any(h in url for h in ("nc.example", "talk.example")):
                    continue
                if f.startswith("src/") and any(p in url for p in ("owncloud.org/ns", "urn:ietf:")):
                    continue
                bad_urls.append(f"{f}:{i}: {url}")
    check("no URL literals outside src/client.py (except XML namespaces / mock hosts)", not bad_urls, "; ".join(bad_urls[:5]))

    # 3. request-path construction in changed tools modules
    for f, text in texts.items():
        if f.startswith("src/tools_"):
            for m in re.finditer(r"client\.(?:request|ocs|propfind|dav_get|dav_put|dav_mkcol|dav_move|dav_delete|dav_proppatch)\(([^;]*?)\)", text, re.S):
                call = m.group(1)
                if re.search(r"\{[^}]*\bargs\b|\+ *args\b|args\.get\(", call):
                    check(f"request path in {f} built via enc_path helpers, not raw args", False, call.strip()[:120])
    check("changed tools modules build request paths via enc_path helpers", all("raw args" not in x for x in failures))
    client_text = (ROOT / "src" / "client.py").read_text(encoding="utf-8")
    check("src/client.py still rejects '..' traversal before any request", "path traversal rejected" in client_text)
    misc_text = (ROOT / "src" / "tools_misc.py").read_text(encoding="utf-8")
    check("nc_ocs still rejects leading '/' and '..' before any request", "traversal rejected" in misc_text)

    # 4. read-back verification on write/destructive tools (ast-parsed)
    guard_src = (ROOT / "src" / "guardrails.py").read_text(encoding="utf-8")
    guard_tree = ast.parse(guard_src)
    sets: dict[str, set] = {}
    for node in guard_tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "frozenset":
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value.args[0], ast.Set):
                    sets[t.id] = {e.value for e in node.value.args[0].elts if isinstance(e, ast.Constant)}
    writes = sets.get("WRITES", set()) | sets.get("DESTRUCTIVE", set())
    tools_src = {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / "src").glob("tools_*.py"))}
    all_tools: dict[str, tuple[str, str, str]] = {}
    for fname, text in tools_src.items():
        tree = ast.parse(text)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in node.targets):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Tuple) and isinstance(elt.elts[0], ast.Constant) and isinstance(elt.elts[2], ast.Call) and elt.elts[2].args:
                        inner = elt.elts[2].args[0]
                        fn = inner.id if isinstance(inner, ast.Name) else ""
                        fndef = funcs.get(fn)
                        src = ast.get_source_segment(text, fndef) if fndef else ""
                        all_tools[elt.elts[0].value] = (fname, fn, src or "")
    all_funcs = {}
    for fname, text in tools_src.items():
        tree = ast.parse(text)
        all_funcs[fname] = (text, {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)})
    for tool in sorted(writes):
        if tool == "nc_ocs":  # arg-dispatch generic OCS escape hatch — gated as write; no generic read-back possible
            continue
        loc = all_tools.get(tool)
        if not loc:
            check(f"{tool} handler found for verification check", False, "not in any TOOLS list")
            continue
        text, funcs = all_funcs[loc[0]]
        src = loc[2]
        for called in set(re.findall(r"\b(_\w+)\(", src)):  # follow one level of module-local helpers (e.g. _tag_set)
            fndef = funcs.get(called)
            if fndef:
                src += "\n" + (ast.get_source_segment(text, fndef) or "")
        check(f"{tool} (write/destructive) read-back verifies", "verif" in src.lower(), f"handler {loc[1]} in {loc[0]} lacks verification")

    # 5. wiring: schema + plugin.yaml + guardrails classification for every tool
    schemas_src = (ROOT / "src" / "schemas.py").read_text(encoding="utf-8")
    schema_names = set(re.findall(r"^(NC_\w+)\s*=", schemas_src, re.M))
    yaml_text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    provides = set()
    in_block = False
    for line in yaml_text.splitlines():
        if re.match(r"^provides_tools:", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^[a-z_]+:", line):
                break
            mm = re.match(r"^\s+-\s+(\w+)\s*$", line)
            if mm:
                provides.add(mm.group(1))
    guard_classified = set(sets.get("READ_ONLY", set())) | set(sets.get("WRITES", set())) | set(sets.get("DESTRUCTIVE", set()))
    guard_classified |= set(re.findall(r'"(nc_\w+)"', guard_src))
    for tool in sorted(all_tools):
        const = re.sub(r"^nc_", "NC_", tool).upper()
        check(f"{tool} has schema {const}", const in schema_names)
        check(f"{tool} in plugin.yaml provides_tools", tool in provides)
        check(f"{tool} classified in guardrails.py", tool in guard_classified)

    # 6. tests hermetic
    for f, text in texts.items():
        if f.startswith("tests/"):
            if "httpx.Client(" in text and "MockTransport" not in text:
                check(f"{f} uses MockTransport only", False, "httpx.Client without MockTransport")
            for pat in (r"import socket", r"socket\.socket", r"urllib\.request", r"\brequests\."):
                if re.search(pat, text):
                    check(f"{f} hermetic (no {pat})", False, "found real-network construct")
            for m2 in URL_RE.finditer(text):
                if not any(h in m2.group(0) for h in ("nc.example", "talk.example")):
                    check(f"{f} only mock-host URLs", False, m2.group(0))
    check("changed tests stay MockTransport-only", all("MockTransport" not in x and "hermetic" not in x and "mock-host" not in x for x in failures))

    # 7. dependencies
    m = re.search(r"^python_dependencies:\n((?:\s+-\s+\S+\n)+)", yaml_text, re.M)
    deps = re.findall(r"-\s+(\S+)", m.group(1)) if m else []
    check("plugin.yaml python_dependencies == [httpx]", deps == ["httpx"], str(deps))
    stdlib = set(sys.stdlib_module_names)
    for f, text in texts.items():
        if f.startswith("src/") and f.endswith(".py"):
            tree = ast.parse(text)
            for node in ast.walk(tree):
                mod = None
                if isinstance(node, ast.Import):
                    mod = node.names[0].name.split(".")[0]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mod = node.module.split(".")[0]
                if mod and mod not in stdlib and mod not in ("httpx", "agent", "nextcloud_tools"):
                    check(f"no third-party imports in {f}", False, f"import {mod}")
    check("changed src files import only stdlib/httpx/agent/relative", all("third-party" not in x for x in failures))

    # 8. guardrail registration
    init_src = (ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    check('src/__init__.py registers pre_tool_call hook', 'register_hook("pre_tool_call"' in init_src)
    check("src/guardrails.py defines guard", "def guard(" in guard_src)

    if failures:
        print(f"FAIL security-invariants: {len(failures)} check(s) failed")
        return 1
    print("PASS security-invariants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
