---
name: nc-compat-hermes
description: Check nextcloud-hermes-tools against the Hermes Agent plugin contract — run after every Hermes upgrade and before any release (contract doc, releases, plugins compat/validate/doctor, agent startup log, dashboard tab, httpx surface, repo checks); records the checked-against Hermes version in last-checked.json
---

# Checking Hermes compatibility

Run top-to-bottom after every Hermes Agent upgrade (`pip`/`git pull` of
NousResearch/hermes-agent) and before any plugin release. Every step ends in an
observable pass/fail. The checked-against version is recorded in
`.omp/skills/nc-compat-hermes/last-checked.json` at the end (step 12) and reported at
the start of the next run (step 1).
1. **Report the last recorded check.** Read
   `.omp/skills/nc-compat-hermes/last-checked.json` if it exists and state its
   `target_version`, `checked_at`, and `result`.
   - Guardrail: a missing or corrupt file means "never checked" — report that and
     continue; do not fail, do not guess.
2. **Check for a newer Hermes version.** Fetch the latest release tag of
   `NousResearch/hermes-agent` (GitHub releases), strip the leading `v`, parse
   it with the same leading-integer-component rule as `parse_version` in
   `src/compat.py`, and compare the tuple against `HERMES_TESTED` in
   `src/compat.py` and `target_version` in `last-checked.json`.
   - If the latest tag is newer: run steps 3–10 against that version and ONLY
     on final result `pass` set `HERMES_TESTED` in `src/compat.py` to the new
     tag's (major, minor); record via step 12.
   - If it is not newer, or the run ends `fail`: leave `HERMES_TESTED`
     unchanged and name the reason in `notes`.
3. **Read the contract and the release notes.**
   - Guidance: open https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
     and the GitHub releases of NousResearch/hermes-agent (tags like `v2026.9.24`).
     The native plugin contract is behavior-based, not versioned: no
     `PLUGIN_API_VERSION`; documented `PluginContext` methods are never removed or
     renamed; new parameters are optional keyword-only; hook payloads grow only by
     added keyword fields; unknown `plugin.yaml` fields are ignored by older Hermes.
     Deprecation policy: a deprecated behavior ships a replacement + a once-per-process
     WARNING and stays supported through >= 2 subsequent minor releases — scan release
     notes for deprecations naming surfaces this plugin uses.
   - Guardrails: MUST NOT import Hermes internals or monkey-patch core modules (the
     plugin catalog refuses "no core override"; internal import paths from before the
     Sep-2026 module decomposition, PR #102117, were removed 2026-09-14). Use only
     documented `ctx.*` methods and `agent.secret_scope.get_secret_str`.
4. **Verify the exact `ctx` surface used in code against the doc.**
   - Guidance: `grep -n "ctx\.\|from agent" src/` — expect exactly
     `ctx.register_tool(name=, toolset=, schema=, handler=, check_fn=, requires_env=, description=)`
     (`src/__init__.py:50`), `ctx.register_hook("pre_tool_call", guard)`
     (`src/__init__.py:59`), `ctx.get_config(key, default)` (`src/__init__.py:33`),
     `from agent.secret_scope import get_secret_str` (`src/client.py:70`). If the doc
     renamed/removed one, migrate every callsite in the same change (clean cutover, no
     aliases). Keep `guard(tool_name="", args=None, **_)` in `src/guardrails.py:73`
     accepting `**kwargs` (payloads are additive) and never raising — a raise fails
     closed and blocks every `nc_*` tool; on internal error fail toward `approve`.
   - Guardrail: `pre_tool_call` is a directive hook (any valid block wins over any
     approve); its return stays `None` or `{"action": "approve"|"block", ...}`.
5. **Scan for removed internal import paths.** Run
   `hermes plugins compat [--json] <repo root>` — MUST exit 0. Any hit: fix the import
   per hermes-agent `COMPAT_MANIFEST.md` before continuing.
6. **Run the catalog checks.** `hermes plugins validate <repo root> --install-deps`
   and `hermes plugins doctor nextcloud-tools` — both MUST pass.
7. **Load check in a real agent.** `hermes plugins list` (no load errors), then start
  the agent once: expect the log line `nextcloud-tools registered 44 tools, 0 disabled`
   (fewer only if `disabled_tools` is configured) and grep `agent.log`/`errors.log` for
   once-per-process WARNINGs naming this plugin (deprecations, legacy hook envelope).
   - Guardrail: an `ImportError` at load means a stale host import path — fix per step 5
     first; do not work around it.
8. **Dashboard tab contract.** `dashboard/manifest.json`
   (`name/label/icon/version/tab/entry/api`) and the wire contract between
   `dashboard/plugin_api.py` (`GET /tools`, `PUT /tools/{name}`) and
   `dashboard/dist/index.js` MUST still match the host contract in
   https://hermes-agent.nousresearch.com/docs/user-guide/features/extending-the-dashboard.
   - Guardrails: `manifest.json` `version` is the dashboard tab's own version — MUST NOT
     be synced with `plugin.yaml` `version`. `plugin_api.py` stays host-only: never
     imported from the CLI plugin or tests.
9. **httpx surface.** Only `Client`/`request`/`MockTransport` are used; `httpx` is a
   Hermes core dep declared in `python_dependencies` (`plugin.yaml:21`). Keep the lazy
   import in `src/client.py` so the package imports with the stdlib alone. Watch httpx
   releases for changes in that used surface.
10. **Repo checks.** `.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py`
   and `.venv/bin/python -m pytest tests -q` — MUST pass (tests are hermetic
   `httpx.MockTransport` only).
11. **Version plumbing.** Every commit MUST bump `version:` in `plugin.yaml` line 2 —
    that is how `hermes plugins update` sees the new plugin (see the `nc-commit` skill).
12. **Record this check.** Write `.omp/skills/nc-compat-hermes/last-checked.json` as a
    single JSON object with exactly these five keys (example):
    ```json
    {"skill": "nc-compat-hermes", "checked_at": "2026-11-07",
     "target_version": "v2026.9.24", "result": "pass", "notes": ""}
    ```
    `checked_at` = today's date (`YYYY-MM-DD`); `target_version` = the running Hermes
    version string (`hermes --version` output; if that flag is unavailable, the
    installed `hermes-agent` distribution version — confirm the exact flag at runtime,
    unverified); `result` = `"pass"` only if steps 3–10 all passed, else `"fail"`;
    `notes` = one line naming any deprecation or failure found (may be empty).
    - Guardrails: write the file last, after all checks; exactly five keys, no extras;
      never hand-edit it between runs; the file stays untracked via the `.gitignore`
      line `.omp/skills/*/last-checked.json` — MUST NOT be committed; on `pass`,
      `HERMES_TESTED` in `src/compat.py` MUST equal (major, minor) of `target_version`.
