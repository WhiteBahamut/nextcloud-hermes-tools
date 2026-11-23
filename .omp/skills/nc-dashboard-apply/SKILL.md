---
name: nc-dashboard-apply
description: Expert runbook for applying reviewed changes to the nextcloud-tools dashboard tab safely — diff discipline, ES5/token/AA edit rules, SDK-surface and wire-contract sync, contrast-guard authoring, deterministic verification + mock smoke, and commit / version-bump / rollback rules. Used by the dashboard-designer agent in apply mode.
---

# Applying dashboard changes

## Scope

Edit `dashboard/dist/index.js` and `dashboard/dist/style.css` directly — there
is no build step. Touch `dashboard/plugin_api.py`, `dashboard/manifest.json`,
`mock/`, or `tests/test_dashboard_contrast.py` only when the wire contract,
the manifest, the SDK surface, or the style guard actually changes.

## Diff discipline

- Re-read the target file before every edit (anchors shift after each edit); if
  a multi-part edit is rejected, apply it as separate single edits; NEVER guess
  line numbers or edit from memory.
- Minimal diffs: change only what the proposal says. NEVER reformat, reindent,
  or "clean up" untouched code — match the surrounding style by hand (there is
  no formatter; `AGENTS.md`).
- Keep the header comments in sync: the SDK contract and wire contract
  documented at the top of `index.js` and in the `plugin_api.py` docstring MUST
  match reality after the change.
- One logical change per commit.

## Edit rules for the bundle (`dist/index.js`)

- ES5 style only: `var` / `function`, string concat — no arrow functions, no
  template literals, no `const`/`let`, no `import`/`export` (enforced by
  `run_all.sh` layer 1 and `node --check`).
- Every `nc-*` class referenced in a string literal MUST have a selector in
  `style.css` (enforced; `nc-group`/`nc-req` are the documented layout-only
  exceptions — re-review that allowlist when the bundle changes).
- New SDK members: extend `mock/mock_sdk.js` in the SAME commit (the SDK-surface
  check fails otherwise) and keep a defensive runtime fallback for older hosts
  (the `cn` / `useToastSafe` / `fetchJSON` / `Checkbox`-or-`Button` pattern).
- State updates that can race MUST use functional updates
  (`setExpanded(function (prev) { … })`); only one PUT in flight at a time;
  refetch after every PUT (GET is authoritative); keep expansion in
  localStorage key `nc-tools-expanded-v1`.

## Edit rules for the stylesheet (`dist/style.css`)

- New colors MUST be `var(--color-*, var(--*))` token chains — NEVER hex/rgb/hsl
  literals. Put a plain fallback declaration BEFORE any `color-mix()`.
- Badge-like elements: keep the opaque-pill pattern with two-class selectors
  (`.nc-row .nc-gatebadge`) so host tone classes lose regardless of stylesheet
  order; destructive/mixed tints stay at `color-mix(destructive 25%, card)`.
- Status on numbers is forbidden: non-text signals only (borders ≥ 3:1).
- New text MUST be ≥ 0.75rem and pass AA under the pinned nord tokens AND hold
  under the mock's light theme. Add a `TEXT_CASES` entry
  `(name, [[root classes]…[target classes]])` to
  `tests/test_dashboard_contrast.py` for every new text-bearing selector, and
  a `floor_selectors` entry in `test_font_size_floor` for small text — in the
  same commit. On failure the test prints the measured ratio, e.g.
  `gate badge base: 3.55:1 (#ECEFF4 on #BF616A) < 4.5:1` — fix the token chain,
  never the assertion.
- New interactive elements MUST have `:focus-visible` (ring) + aria; rows keep
  `:focus-within`; respect the 52rem / 40rem breakpoints and
  `prefers-reduced-motion`.
- Keep `.nc-row` and `.nc-cols` on the same `grid-template-columns`; fixed-width
  expand glyph (no layout shift).

## Wire contract sync (all sides, same commit)

If an endpoint or field changes, update `dist/index.js`, `plugin_api.py`,
`mock/mock_server.py`, and `mock/README.md` together — never one side only.
`plugin_api.py` stays host-only: never imported from the CLI plugin or tests.

## Verification (run from the repo root; offline/deterministic)

1. `node --check dashboard/dist/index.js` (when node is available).
2. `bash .omp/agents/dashboard-designer/scripts/run_all.sh` — bundle invariants
   + `node --check` + contrast guard when `.venv` exists; quote PASS/FAIL.
3. `.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py` (create the
   venv per `AGENTS.md` → "Do this first" if missing; never install anything
   beyond `httpx pytest`).
4. `.venv/bin/python -m pytest tests -q` — MUST be green.
5. Mock smoke: start `python3 mock/mock_server.py --port 8787` in the
   background, then via python urllib (the no-curl rule is for Nextcloud APIs,
   not the local mock): `GET /api/plugins/nextcloud-tools/tools` returns
   `{"tools": [...]}` with all 52 `nc_*` tools; `PUT .../tools/nc_file_get`
   `{"enabled": false}` then `true` → `{"ok": true}` and the GET reflects it;
   `PUT .../tools/nc_file_get/guardrails` `{"enabled": false}` then `true`;
   an unknown name (e.g. `nc_nope`) → 400. Kill the server, delete
   `mock/state.json`.
6. Visual smoke: headless screenshots of the mock at 1440/900/390px in the
   default light theme (chrome binary under `.omp/puppeteer/chrome/`) and eyeball
   them against the proposal.

## Commit and rollback

- Conventional commit per the `nc-commit` skill; the Mistral Vibe commit heredoc
  with the co-author trailer.
- EVERY commit bumps `version:` on line 2 of `plugin.yaml` (feat → minor,
  fix/perf/security/docs → patch, breaking → major).
- Bump `dashboard/manifest.json` `version` only when the shipped tab itself
  changed; NEVER sync it with the plugin version.
- Before committing: run the `nc-security-audit` subagent (dashboard/ changed)
  and the `nc-tool-review` subagent when `src/` is also touched (via the task
  tool); any blocker finding MUST be fixed first.
- Rollback: `git revert` the commit (the revert is itself a commit, so it also
  carries the mandatory `plugin.yaml` version bump per `nc-commit`).
