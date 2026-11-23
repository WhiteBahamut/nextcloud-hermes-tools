---
name: nc-dashboard-foundations
description: Architecture and hard invariants of the nextcloud-tools Hermes dashboard tab — file layout, build-less ES5 bundle, __HERMES_PLUGIN_SDK__ contract, plugin_api.py wire contract, theme tokens + WCAG AA rules, mock harness, and tests. Source of truth before reviewing, designing, or changing anything under dashboard/ or mock/.
---

# Dashboard foundations — nextcloud-tools tab

This skill is the source of truth for how the dashboard tab is built and which
invariants MUST hold in every change. Read it before reviewing, designing, or
editing anything under `dashboard/` or `mock/`. `AGENTS.md` is the repo-level
source of truth and is not repeated here.

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
| `dashboard/dist/index.js` | the tab, plain IIFE bundle | no build step, no imports, ES5-style (`var`/`function`, string concat); registered via `window.__HERMES_PLUGINS__.register("nextcloud-tools", Page)` — the name MUST match manifest `name` |
| `dashboard/dist/style.css` | all tab styles | theme tokens only — NO hex/rgb/hsl literals |
| `dashboard/plugin_api.py` | host-only fastapi router | MUST NOT be imported from the CLI plugin or the test suite |
| `mock/` | manual-testing harness (stdlib server + mock SDK) | opens a real socket, so it MUST NOT live under `tests/`; runtime state in git-ignored `mock/state.json` |
| `src/dashboard_store.py` | per-tool enable/gate persistence + live tool docs | shared by `plugin_api.py` and the mock |
| `tests/test_dashboard_contrast.py` | WCAG AA + font-floor guard for `style.css` | stdlib-only, offline; extend its selector matrix when adding text-bearing selectors |

## Hermes plugin SDK contract

`dist/index.js` consumes exactly this surface of
`window.__HERMES_PLUGIN_SDK__` (verified against the pinned Hermes tag,
@nous-research/ui); `mock/mock_sdk.js` implements the same surface:

- `React.createElement` / `React.Fragment`
- hooks: `useState` / `useEffect` / `useMemo` / `useToast`
- `utils.cn`
- components: `Card`, `CardHeader`, `CardTitle`, `CardContent`, `Badge` (`tone`
  prop: default|secondary|outline|destructive|success|warning), `Button`
  (boolean flags `destructive`/`ghost`/`invert`/`outlined` + `size`
  xs|sm|default|icon), `Checkbox` (Radix: `checked`/`onCheckedChange`),
  `Tabs` (**render-prop**: `children(active, setActive)` + `defaultValue`, no
  `TabsContent`), `TabsTrigger({value, active, onClick})`, `TabsList`,
  `Select({value, onValueChange})` + `SelectOption({value})`, `Separator`,
  `Input`, `Toast({toast})`
- `SDK.fetchJSON` (auth-injecting, throws on !ok, parses JSON)

Anything outside this surface MUST get a defensive runtime fallback (the
existing `cn` / `useToastSafe` / `fetchJSON` / `Checkbox`-or-`Button` fallbacks
in `index.js` are the pattern) — never assume a newer host.

## Wire contract (never rename one side only)

`dashboard/plugin_api.py` (docstring) ↔ `dist/index.js` (header comment) ↔
`mock/mock_server.py` + `mock/README.md`:

- `GET /api/plugins/nextcloud-tools/tools` → `{"tools": [{"name", "description",
  "parameters", "gate", "enabled", "guarded"}]}`
- `PUT /api/plugins/nextcloud-tools/tools/{name}` body `{"enabled": bool}` →
  `{"ok": true, "disabled_tools": [...]}`
- `PUT .../tools/{name}/guardrails` body `{"enabled": bool}` (enabled = gate ON)
  → `{"ok": true, "ungated_tools": [...]}`
- unknown tool → `400 {"detail": "unknown nc_* tool: ..."}`

Behavioral invariants: after every PUT the tab refetches (the GET payload is
authoritative); only one PUT is in flight at a time (config write race);
"enabled" applies on the next agent start, the gate toggle applies immediately.

## Theming + accessibility invariants

- Every color comes from host tokens: `var(--color-x, var(--x))` fallback
  chains, plus `--radius` and `--theme-font-mono`. `style.css` MUST NOT contain
  hex/rgb/hsl literals — the plugin ships no color theme of its own.
- WCAG AA under the pinned nord tokens (enforced by
  `tests/test_dashboard_contrast.py`): text ≥ 4.5:1, non-text signals ≥ 3:1;
  plugin-authored text ≥ 0.75rem (the 11px floor); status is carried by a
  non-text signal (e.g. a colored left border), never by sub-AA colored text;
  a `color-mix()` declaration MUST be preceded by a plain fallback declaration;
  `prefers-reduced-motion` MUST be respected.
- Every plugin interactive element MUST have a `:focus-visible` ring
  (`--color-ring`) and the right aria (`aria-expanded`, `aria-pressed`,
  `aria-label`, `role="alert"` on banners and confirm strips).

## Interaction + state invariants

- Distinct loading (skeleton), error (panel + Retry), and empty states.
- A warning banner shows whenever destructive/mixed tools are ungated; ungating
  a destructive/mixed tool requires the inline confirm strip (a repeat toggle
  click cancels; only the confirm button ungates — no double-click bypass).
- Expanded rows persist in localStorage key `nc-tools-expanded-v1`; toasts go
  through `useToast` with an inline-error fallback on older hosts.
- The row grid (`.nc-row`) and the column header (`.nc-cols`) share the same
  `grid-template-columns`; the expand button is fixed-width so rows never shift.

## Testing + verification

- Tests are `httpx.MockTransport`-only, no real sockets; the dashboard style
  guard is `tests/test_dashboard_contrast.py` (offline: stdlib regex CSS parse
  + WCAG relative-luminance math against pinned nord tokens).
- Manual UI pass: `python3 mock/mock_server.py` — serves the real `dist/`
  bundle against the mock SDK; open the printed URL.
- Syntax: `node --check dashboard/dist/index.js` when node is available.
- Bundle invariants:
  `bash .omp/agents/dashboard-designer/scripts/run_all.sh` (ES5 lint, no color
  literals, wire-contract strings on all three sides, manifest↔register name,
  SDK surface covered by the mock, `nc-*` classes defined in the CSS, font
  floor, focus/reduced-motion rules, contrast guard).
