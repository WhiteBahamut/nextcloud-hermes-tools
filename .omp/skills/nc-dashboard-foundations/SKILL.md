---
name: nc-dashboard-foundations
description: Architecture, design language, and hard invariants of the nextcloud-tools Hermes dashboard tab — file layout, build-less ES5 bundle, __HERMES_PLUGIN_SDK__ contract, plugin_api.py wire contract, semantic theme tokens + WCAG AA rules across light AND dark host themes, mock harness, and tests. Source of truth before reviewing, designing, or changing anything under dashboard/ or mock/.
---

# Dashboard foundations — nextcloud-tools tab

This skill is the source of truth for how the dashboard tab is built, what it
currently looks like, and which invariants MUST hold in every change. Read it
before reviewing, designing, or editing anything under `dashboard/` or `mock/`.
`AGENTS.md` is the repo-level source of truth and is not repeated here.

## What the tab is

A Hermes Agent **plugin dashboard tab**: `dashboard/manifest.json` declares
`name: "nextcloud-tools"`, label "Nextcloud", `tab.path: "/nextcloud-tools"`,
`tab.position: "end"`, `entry: "dist/index.js"`, `css: "dist/style.css"`,
`api: "plugin_api.py"`. The host loads `dist/index.js` + `dist/style.css` and
mounts `plugin_api.py` (fastapi) at `/api/plugins/nextcloud-tools/`.

## File map

| Path | Role | Rules |
|---|---|---|
| `dashboard/manifest.json` | tab manifest | `version` is the tab's own — bump only when the shipped tab changes; NEVER sync it with the `plugin.yaml` version |
| `dashboard/dist/index.js` | the tab, plain IIFE bundle (~830 lines) | no build step, no imports, ES5-style (`var`/`function`, string concat); registered via `window.__HERMES_PLUGINS__.register("nextcloud-tools", Page)` — the name MUST match manifest `name` |
| `dashboard/dist/style.css` | all tab styles (~590 lines) | theme tokens only — NO hex/rgb/hsl literals |
| `dashboard/plugin_api.py` | host-only fastapi router | MUST NOT be imported from the CLI plugin or the test suite |
| `mock/` | manual-testing harness: `mock_server.py` (stdlib, default `http://127.0.0.1:8787/`) + `index.html` (light zinc theme tokens) + `mock_sdk.js` (mini-React + all SDK components) | opens a real socket, so it MUST NOT live under `tests/`; runtime state in git-ignored `mock/state.json` |
| `src/dashboard_store.py` | per-tool enable/gate persistence + live tool docs from `src/schemas.py` | shared by `plugin_api.py` and the mock; unknown tool raises `ValueError("unknown nc_* tool: ...")` → HTTP 400 |
| `tests/test_dashboard_contrast.py` | WCAG AA + font-floor guard for `style.css` | stdlib-only, offline; extend `TEXT_CASES` / `floor_selectors` when adding text-bearing selectors |

## Current design language (what you are redesigning)

Information architecture, top to bottom inside one host `Card`:

```
CardHeader   title "Nextcloud tools" + lede + stat strip
             (Tools / Enabled / Approval-gated / Ungated — 4-up grid, muted
             tiles, status as a 3px left border, never colored numbers)
             + gate-class breakdown line full-width below the stat cards
             ("22 read · 22 write · …")
CardContent  warning banner (destructive/mixed ungated) · collapsible
             <details> explainer · nav panel (one
             bordered panel with hairline-divided rows, all the same style:
             a search row with the Input pill, then one row per pill group —
             CATEGORY (All tools + one pill per category), GATE and STATE
             micro-labels, each leading its own pill group; pills carry faceted
             counts (each group counted within the other groups' selections,
             never its own) and are disabled at 0 except the "All …" reset pill)
             · list bar over the list (result count "Showing X of N" left;
             expand-all / collapse-all / reload action pills top right) ·
             uppercase column header · rows (or per-category group headers
             for the All-tools pill)
Row          [▸ expand] tool name (mono) + 1-line desc · gate pill · Enabled
             toggle · Approval-gate toggle (row text captions hidden above
             40rem — the column header carries them; they return at <=40rem)
Row expanded doc panel: description · copyable call signature · parameter
             cards (mono name · type pill · required badge · default · desc)
Inline strip destructive-ungate confirmation (role=alert)
```

- Typography scale: 0.75rem uppercase micro-labels (letter-spacing 0.04em),
  0.8125rem secondary, 0.875rem body/names, 1.25rem stat values; code in
  `var(--theme-font-mono, var(--font-mono, …))`. Floor: 0.75rem, always.
- Spacing on a 0.25rem base; row/column grid
  `1.5rem minmax(0,1fr) 6.5rem 7.5rem 9.5rem` shared by `.nc-row` and `.nc-cols`;
  radius from `var(--radius, var(--radius-md, 0.5rem))`.
- Breakpoints: 52rem (stats 2-up, actions wrap) and 40rem (column header
  hidden, rows wrap to two lines, description clamps to 2 lines).
- States: skeleton rows (pulse, disabled under `prefers-reduced-motion`), error
  panel with Retry, distinct empty states ("No tools registered." vs "No tools
  match the current filters.").

## Semantic theme tokens (design against every host theme, not one)

The host supplies the `--color-*` family (with unprefixed shadcn fallbacks):
`background`, `foreground`, `card`, `card-foreground`, `muted`,
`muted-foreground`, `primary`, `primary-foreground`, `border`, `ring`,
`destructive`, `destructive-foreground`, `success`, `warning`, plus
`--radius*` and `--theme-font-mono`/`--font-mono`.

Rules that exist because of measured failures:

- `style.css` MUST NOT contain hex/rgb/hsl literals — the plugin ships no
  color theme of its own. The guard test pins the nord (dark) tokens; the mock
  ships a light zinc theme — so a change MUST hold under BOTH. Never tune
  contrast for one theme only.
- Host `Badge` tones fail AA on dark themes at badge size (secondary/outline
  render muted-foreground on muted; solid destructive is 3.55:1 under nord).
  The tab forces an opaque pill (foreground on muted = 6.39:1) with
  **two-class selectors** (`.nc-row .nc-gatebadge`) so it beats the host's
  single-class tone rules regardless of stylesheet order; destructive/mixed
  get a `color-mix(destructive 25%, card)` background (6.04:1). Preserve this
  pattern for any new badge-like element.
- Status on stat tiles is a non-text signal (3px left border ≥ 3:1), never a
  colored number (success on muted was 4.23:1 = FAIL). Keep it that way.
- A `color-mix()` declaration MUST be preceded by a plain fallback declaration
  (older engines ignore the mix and keep the fallback).
- WCAG AA under the pinned nord tokens (enforced by
  `tests/test_dashboard_contrast.py`): text ≥ 4.5:1, non-text signals ≥ 3:1,
  font floor 0.75rem. When you add a text-bearing selector, add a
  `(name, [[root classes]…[target classes]])` entry to `TEXT_CASES` (and to
  `floor_selectors` in `test_font_size_floor` for small text) in the same
  commit.
- Every plugin interactive element MUST have a `:focus-visible` ring
  (`--color-ring`) and the right aria (`aria-expanded`, `aria-pressed`,
  `aria-label`, `role="alert"`/`role="region"` on banners, confirm strips, and
  detail panels). Rows also get `:focus-within` outlines.

## Hermes plugin SDK contract

`dist/index.js` consumes exactly this surface of
`window.__HERMES_PLUGIN_SDK__` (verified against the pinned Hermes tag,
@nous-research/ui); `mock/mock_sdk.js` implements at least this surface:

- `React.createElement` / `React.Fragment`
- hooks: `useState` / `useEffect` / `useMemo` / `useToast` (toast auto-dismiss
  ~3.5s in the mock)
- `utils.cn`
- components: `Card`, `CardHeader`, `CardTitle`, `CardContent`, `Badge` (`tone`
  prop: default|secondary|outline|destructive|success|warning), `Button`
  (boolean flags `destructive`/`ghost`/`invert`/`outlined` + `size`
  xs|sm|default|icon), `Checkbox` (Radix: `checked`/`onCheckedChange`),
  `Input`, `Toast({toast})`
- `SDK.fetchJSON` (auth-injecting, throws on !ok, parses JSON)

Anything outside this surface MUST get a defensive runtime fallback (the
existing `cn` / `useToastSafe` / `fetchJSON` / `Checkbox`-or-`Button` fallbacks
in `index.js` are the pattern) — never assume a newer host. If the tab starts
using a new SDK member, extend `mock/mock_sdk.js` in the SAME commit — the
`run_all.sh` SDK-surface check fails otherwise.

## Wire contract (never rename one side only)

`dashboard/plugin_api.py` (docstring) ↔ `dist/index.js` (header comment) ↔
`mock/mock_server.py` + `mock/README.md`:

- `GET /api/plugins/nextcloud-tools/tools` → `{"tools": [{"name", "description",
  "parameters", "gate", "enabled", "guarded"}]}` — descriptions and parameter
  docs come LIVE from `src/schemas.py` via `dashboard_store.tool_doc`; never
  duplicate a docs table in the bundle
- `PUT /api/plugins/nextcloud-tools/tools/{name}` body `{"enabled": bool}` →
  `{"ok": true, "disabled_tools": [...]}`
- `PUT .../tools/{name}/guardrails` body `{"enabled": bool}` (enabled = gate ON)
  → `{"ok": true, "ungated_tools": [...]}`
- unknown tool → `400 {"detail": "unknown nc_* tool: '...'"}`

Behavioral invariants: after every PUT the tab refetches (the GET payload is
authoritative); only one PUT is in flight at a time (config write race);
"enabled" applies on the next agent start, the gate toggle applies immediately.

## State, persistence, and mock-renderer quirks

- Expanded rows persist in localStorage key `nc-tools-expanded-v1` (guarded
  try/catch for private mode); updates use functional `setExpanded(prev => …)`
  so batched events never overwrite each other.
- The mock's mini-React keys hook state by component path (fine for this single
  page); the search input's focus/selection is restored across rebuilds. When
  reviewing interaction bugs in the mock, check whether the bug is in
  `dist/index.js` or in these mock limitations before reporting it.
- Filtering/search is client-side over the fetched list — no refetch per
  keystroke.

## Testing + verification

- Tests are `httpx.MockTransport`-only, no real sockets; the dashboard style
  guard is `tests/test_dashboard_contrast.py` (offline: stdlib regex CSS parse,
  cascade resolution, WCAG relative-luminance math against pinned nord tokens,
  plus the 0.75rem floor test).
- Manual UI pass: `python3 mock/mock_server.py` (serves the real `dist/`
  bundle against the mock SDK), open the printed URL; screenshots via the
  headless chrome at `.omp/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome`.
- Syntax: `node --check dashboard/dist/index.js` when node is available.
- Bundle invariants:
  `bash .omp/agents/dashboard-designer/scripts/run_all.sh` (ES5 lint, no color
  literals, font floor, a11y scaffolding, wire-contract strings on all sides,
  manifest↔register name, SDK surface covered by the mock, `nc-*` classes
  defined in the CSS, contrast guard, `node --check`).
