---
name: nc-dashboard-apply
description: Runbook for applying reviewed changes to the nextcloud-tools dashboard tab safely — edit rules, wire-contract sync, deterministic verification, mock smoke test, and commit + version-bump rules. Used by the dashboard-designer agent in apply mode.
---

# Applying dashboard changes

## Scope and edit rules

- Edit `dashboard/dist/index.js` and `dashboard/dist/style.css` directly — there
  is no build step. Touch `dashboard/plugin_api.py`, `dashboard/manifest.json`,
  and `mock/` only when the wire contract or the manifest actually changes.
- Re-read the target file before every edit (anchors shift after each edit); if
  a multi-part edit is rejected, apply it as separate single edits; NEVER guess
  line numbers or edit from memory.
- Keep the ES5 bundle style: `var` / `function`, string concat — no arrow
  functions, no template literals, no `const`/`let`, no `import`/`export`.
- Keep the header comments in sync: the SDK contract and wire contract
  documented at the top of `index.js` and in the `plugin_api.py` docstring MUST
  match reality after the change.
- Every `nc-*` class referenced in `index.js` MUST have a rule in `style.css`;
  every new selector that bears text MUST be added to the contrast-guard matrix
  in `tests/test_dashboard_contrast.py`.
- New colors MUST be `var(--color-*, var(--*))` token chains — NEVER hex/rgb/hsl
  literals; new text MUST be ≥ 0.75rem and pass AA contrast; new interactive
  elements MUST have `:focus-visible` + aria; keep the defensive fallbacks for
  older hosts (the `cn` / `useToastSafe` / `fetchJSON` / `Checkbox` pattern).
- Wire contract: if an endpoint or field changes, update `dist/index.js`,
  `plugin_api.py`, `mock/mock_server.py`, and `mock/README.md` in the SAME
  commit — never one side only. `plugin_api.py` stays host-only: never imported
  from the CLI plugin or the tests.

## Verification (run from the repo root; all offline/deterministic)

1. `node --check dashboard/dist/index.js` (when node is available).
2. `bash .omp/agents/dashboard-designer/scripts/run_all.sh` — bundle invariants
   plus the contrast guard when `.venv` exists; quote its PASS/FAIL lines.
3. `.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py` (create the
   venv per `AGENTS.md` → "Do this first" if missing; never install anything
   beyond `httpx pytest`).
4. `.venv/bin/python -m pytest tests -q` — MUST be green.
5. Mock smoke: start `python3 mock/mock_server.py --port 8787` in the
   background, then via python urllib (the no-curl rule is for Nextcloud APIs,
   not the local mock): `GET /api/plugins/nextcloud-tools/tools` returns
   `{"tools": [...]}` with every `nc_*` tool; one
   `PUT .../tools/nc_file_read` with `{"enabled": false}` then `true` returns
   `{"ok": true}` and the GET reflects it; one
   `PUT .../tools/nc_file_read/guardrails` with `{"enabled": false}` then `true`;
   an unknown tool name returns 400. Kill the server, delete `mock/state.json`.

## Commit

- Conventional commit per the `nc-commit` skill; one logical change per commit;
  the Mistral Vibe commit heredoc with co-author trailer.
- EVERY commit bumps `version:` on line 2 of `plugin.yaml` (feat → minor,
  fix/perf/security/docs → patch, breaking → major).
- Bump `dashboard/manifest.json` `version` only when the shipped tab itself
  changed; NEVER sync it with the plugin version.
- Before committing: run the `nc-security-audit` subagent (dashboard/ changed)
  and the `nc-tool-review` subagent when `src/` is also touched (via the task
  tool); any blocker finding MUST be fixed first.
