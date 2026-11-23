---
name: nc-dashboard-ux-review
description: Expert UX/heuristic + accessibility review runbook for the nextcloud-tools dashboard tab — grounding, mock-harness driving with multi-viewport multi-theme screenshots, a selector-mapped inspection checklist, microcopy and design-critique passes, the severity model, and the findings report format. Used by the dashboard-designer agent in review and improve modes.
---

# Dashboard UX review

## Mission

Review the dashboard tab the way a professional web UI/UX designer would:
information architecture, visual hierarchy, interaction design, states,
responsive behavior, accessibility (WCAG AA), and microcopy. In review mode
MUST NOT edit any file — findings and proposals only. Every finding MUST cite
evidence: `file:line` in the repo, and for visual findings the mock URL +
viewport/theme it was observed at.

## 1. Ground

Read the `nc-dashboard-foundations` skill, `AGENTS.md`, then the FULL
`dashboard/dist/index.js`, `dashboard/dist/style.css`, and
`dashboard/manifest.json`; when the wire contract is in scope also read
`dashboard/plugin_api.py`, `mock/mock_server.py`, `mock/README.md`, and
`tests/test_dashboard_contrast.py`. NEVER review from a diff alone — verify
every claim against the actual files. Run
`bash .omp/agents/dashboard-designer/scripts/run_all.sh` and quote its
PASS/FAIL lines as baseline evidence.

## 2. Drive the mock (manual pass)

```
python3 mock/mock_server.py --port 8787 &        # background; kill afterwards
CHROME=.omp/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome
$CHROME --headless=new --no-sandbox --disable-gpu \
  --screenshot=/tmp/nc-1440.png --window-size=1440,2400 http://127.0.0.1:8787/
# also capture 900px and 390px widths (the 52rem / 40rem breakpoints)
```

The mock's default theme is LIGHT (zinc tokens in `mock/index.html`); the
contrast guard pins nord DARK. Review BOTH: capture the mock as-is, then serve
a throwaway dark wrapper from `/tmp` (same `/dist/style.css` + `/dist/index.js`,
`:root` tokens copied from the `NORD` map in `tests/test_dashboard_contrast.py`)
and screenshot that too. NEVER commit theme overrides into `mock/index.html`.

Click/capture every state: initial load and skeleton, search (incl. the
no-match empty state), gate-class select, each quick-filter chip
(all/disabled/ungated/destructive), category tabs, expand one row +
expand all / collapse all, both toggles (busy `saving…` + toast), the
destructive-ungate confirm strip (confirm AND cancel via repeat toggle click),
copy signature ("Copied ✓"), reload, the warning banner (ungate a destructive
tool via `PUT .../tools/{name}/guardrails`), and the error panel (stop the
server, then Retry). Delete `mock/state.json` afterwards to reset toggles.
When an interaction looks wrong in the mock, first rule out the mock's
mini-React limitations (hook state keyed by component path, module-level Tabs
store — see foundations) before reporting a bundle bug.

## 3. Heuristic pass (Nielsen's ten, adapted to a settings tab)

- visibility of system status: skeleton, `saving…`, toasts, busy row opacity
- match between system and real world: plain labels ("Enabled", "Approval
  gate") + the `<details>` explainer; gate vocabulary Read/Write/Destructive/Mixed
- user control and freedom: cancel paths, collapse all, Retry
- consistency and standards: one gate-pill style, one chip style, one toggle
  pattern, one stat-card pattern
- error prevention: confirm strip before ungating destructive/mixed tools —
  verify no double-click bypass exists
- recognition rather than recall: column header, counts on tabs/chips,
  copyable call signature with defaults
- flexibility and efficiency: search haystack covers name, description,
  category label, gate; filters compose with search
- aesthetic and minimalist design: no walls of text; truncation + 2-line clamp
- help users recognize, diagnose, recover from errors: warning banner, error
  panel with Retry
- accessibility & inclusive design: see section 5

## 4. Design-critique pass (the professional layer)

Inspect the screenshots like a designer, not just a checker:

- Hierarchy: does the eye land title → stats → banner → toolbar → list? Is the
  lede doing work or noise?
- Spacing rhythm: is everything on the 0.25rem base? Are gaps consistent
  within a region (0.375/0.5/0.75/1rem tiers)?
- Alignment: do `.nc-row` cells line up with `.nc-cols` headers (same grid
  template)? Does the expand glyph stay fixed-width (no layout shift)?
- Typography: scale steps (0.75 / 0.8125 / 0.875 / 1.25rem), mono reserved for
  code (names, signatures, types, defaults), uppercase micro-labels at 0.04em
  tracking — is the type doing information design, or is everything the same
  weight?
- Density: 52 tools in one list — are group headers, counts, and truncation
  enough to scan? Would density controls (or virtualization) help, and at what
  cost in the mini-React mock?
- Color discipline: only semantic tokens; status via non-text signals; the
  opaque-pill pattern intact for badges; hover (`--color-muted`) vs
  focus-within ring (`--color-ring`) distinct.
- Microcopy: read every string aloud — title, lede, stat labels, chips,
  explainer, banner, confirm strip ("Ungate without approval" / "Cancel"),
  empty states, error panel, aria-labels, toast verbs ("Enabled nc_…").
  Check tone (plain, imperative), grammar, and that destructive actions say
  exactly what happens.

## 5. Accessibility pass

- Run `tests/test_dashboard_contrast.py` (pinned nord): text ≥ 4.5:1, signals
  ≥ 3:1, 0.75rem floor. For every new/changed text-bearing selector confirm a
  `TEXT_CASES` entry exists; small text also needs a `floor_selectors` entry.
- Multi-theme: re-check any new color usage under the mock's light zinc theme
  too (the guard only pins nord) — screenshots from section 2.
- `:focus-visible` ring on every interactive element (chips, expand buttons,
  copy, summary, toggles via the host Checkbox/Button); `:focus-within` on rows.
- Aria: `aria-expanded` on expand buttons, `aria-pressed` on chips,
  `aria-label` on icon-ish buttons and toggles, `role="alert"` on banner/confirm,
  `role="region"` on the detail panel, `aria-hidden` on the decorative column
  header.
- Keyboard: tab order flows row-by-row; every action reachable and operable
  without a pointer; Escape/Enter behave on native elements.
- Color never the only carrier of meaning; `prefers-reduced-motion` kills the
  skeleton pulse.
- Responsive: at ≤52rem stats go 2-up and actions wrap; at ≤40rem the column
  header hides, rows wrap to two lines, descriptions clamp to 2 lines, detail
  and confirm padding aligns. Check for horizontal overflow at 390px.

## 6. Interaction / contract pass

- One PUT at a time; GET refetch after every PUT (authoritative); failed PUT
  keeps old state and shows an error toast/inline error.
- Wire contract intact on all three sides (`index.js`, `plugin_api.py`,
  `mock/`); every `SDK.*` member used by the bundle is covered by
  `mock_sdk.js` (enforced by `run_all.sh`).
- Expansion persists via localStorage and survives reload; search is
  client-side (no refetch per keystroke).

## Severity

- **blocker**: breaks a hard invariant from `nc-dashboard-foundations` — a
  color literal in `style.css`, wire-contract drift, a contrast / font-floor /
  focus / aria violation, a real socket in tests, `plugin_api.py` imported
  from the CLI plugin or tests, an ES5 / register-name / manifest mismatch, or
  SDK surface the mock does not cover.
- **major**: a UX or a11y regression — a missing state, layout shift,
  keyboard-unreachable control, search/filters missing a field, a confirm
  bypass, contrast that only holds in one theme.
- **minor**: polish — spacing, copy, hover states, ordering, density.

## Report format

One finding per issue: `severity`, `file:line`, `message`, and a concrete
suggested fix (exact class / selector / copy / token var — never vague advice);
visual findings also name the mock viewport + theme. `verdict: pass` only when
no blocker or major findings remain. In improve mode, append a design proposal:
ordered, concrete deltas per file with the expected mock-visible result after
each delta (which screenshot should change and how). In review mode, stop at the
report.
