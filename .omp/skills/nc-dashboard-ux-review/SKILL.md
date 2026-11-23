---
name: nc-dashboard-ux-review
description: UX/heuristic + accessibility review runbook for the nextcloud-tools dashboard tab — what to inspect, how to drive the mock harness, the severity model, and the findings report format. Used by the dashboard-designer agent in review and improve modes.
---

# Dashboard UX review

## Mission

Review the dashboard tab as a professional web UI/UX designer: heuristic
quality, accessibility, states, responsive behavior, and interaction design.
In review mode MUST NOT edit any file — findings and proposals only.

## Method

1. **Ground.** Read the `nc-dashboard-foundations` skill, `AGENTS.md`, then the
   FULL `dashboard/dist/index.js`, `dashboard/dist/style.css`, and
   `dashboard/manifest.json`; when the wire contract is in scope also read
   `dashboard/plugin_api.py`, `mock/mock_server.py`, `mock/README.md`. NEVER
   review from a diff alone — verify every claim against the actual files.
2. **Run the UI.** Start `python3 mock/mock_server.py --port 8787` in the
   background and open http://127.0.0.1:8787/ (optionally screenshot with the
   puppeteer chrome under `.omp/puppeteer/chrome/`). Click through: initial
   load, search, gate-class select, quick-filter chips
   (all/disabled/ungated/destructive), category tabs, expand/collapse one row
   plus expand all / collapse all, both toggles, the destructive-ungate
   confirm strip (including cancel via a repeat toggle click), copy signature,
   reload, and the error path (stop the server, then Retry). Kill the server
   afterwards and delete `mock/state.json` if you toggled tools.
3. **Heuristic pass** (Nielsen's ten, adapted to a settings tab):
   - visibility of system status: skeleton, `saving…`, toasts, busy row
   - match between system and real world: plain labels ("Enabled",
     "Approval gate") + the `<details>` explainer
   - user control and freedom: cancel paths, collapse all, Retry
   - consistency and standards: one gate-pill style, one chip style, one toggle
     pattern, stat cards
   - error prevention: confirm strip before ungating destructive/mixed tools
   - recognition rather than recall: column header, counts on tabs and chips,
     copyable call signature
   - flexibility and efficiency: the search haystack covers name, description,
     category label, and gate
   - aesthetic and minimalist design: no walls of text; truncation plus the
     2-line clamp on descriptions
   - help users recognize, diagnose, and recover from errors: warning banner,
     error panel with Retry
4. **Accessibility pass.** WCAG AA contrast and the 0.75rem floor — run
   `tests/test_dashboard_contrast.py` and extend its selector matrix for every
   new text-bearing selector. Check `:focus-visible` on every interactive
   element, aria attributes (`aria-expanded`, `aria-pressed`, `aria-label`,
   `role="alert"`), keyboard operability of chips/toggles/expand buttons, color
   never the only carrier of meaning, `prefers-reduced-motion`, and the
   responsive behavior at the 52rem and 40rem breakpoints (column header
   hidden, rows wrap, description clamps to 2 lines).
5. **Interaction/contract pass.** One PUT at a time with a refetch after every
   PUT; the wire contract intact on all three sides (`index.js`,
   `plugin_api.py`, `mock/`); every `SDK.*` member used by the bundle is
   covered by `mock_sdk.js`.

## Severity

- **blocker**: breaks a hard invariant from `nc-dashboard-foundations` — a
  color literal in `style.css`, wire-contract drift, a contrast / font-floor /
  focus / aria violation, a real socket in tests, `plugin_api.py` imported
  from the CLI plugin or tests, an ES5 / register-name / manifest mismatch, or
  SDK surface the mock does not cover.
- **major**: a UX or a11y regression — a missing state, layout shift,
  keyboard-unreachable control, search/filters missing a field, a confirm
  bypass.
- **minor**: polish — spacing, copy, hover states, ordering.

## Report format

One finding per issue: `severity`, `file:line`, `message`, and a concrete
suggested fix (exact class / selector / copy / token var — never vague
advice). `verdict: pass` only when no blocker or major findings remain. In
improve mode, append a design proposal: ordered, concrete deltas per file with
the expected mock-visible result after each delta. In review mode, stop at the
report.
