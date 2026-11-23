# Local mock of the dashboard host (nextcloud-tools tab)

Lets you click through the real dashboard UI (`dashboard/dist/index.js` +
`style.css`, unmodified) in a browser without a Hermes host or a Nextcloud
server.

```
python3 mock/mock_server.py          # http://127.0.0.1:8787/
python3 mock/mock_server.py --port 9000
```

Open the printed URL. The page renders the actual `dashboard/dist/` bundle
against a mock `window.__HERMES_PLUGIN_SDK__`.

This folder is a manual-testing harness, not part of the plugin runtime and
not part of the test suite — the server opens a real socket, so it must never
live under `tests/` (tests are `httpx.MockTransport`-only, no real sockets).

| File | Role |
|---|---|
| `mock_server.py` | stdlib-only HTTP server: static files + the plugin API below |
| `index.html` | harness page: theme tokens (`--color-*` / shadcn fallbacks) + mock component chrome |
| `mock_sdk.js` | mini-React (createElement/Fragment, useState/useEffect/useMemo/useToast) + all SDK components the bundle uses + `__HERMES_PLUGINS__.register` |
| `state.json` | runtime toggle state — git-ignored, delete to reset |

## Wire contract (same as `dashboard/plugin_api.py`)

- `GET /api/plugins/nextcloud-tools/tools` → `{"tools": [{name, description, parameters, gate, enabled, guarded}]}`
- `PUT /api/plugins/nextcloud-tools/tools/{name}` body `{"enabled": bool}` → `{"ok": true, "disabled_tools": [...]}`
- `PUT /api/plugins/nextcloud-tools/tools/{name}/guardrails` body `{"enabled": bool}` → `{"ok": true, "ungated_tools": [...]}`
- unknown tool → `400 {"detail": "unknown nc_* tool: ..."}`

Tool names, descriptions, parameter docs and gate classes are read live from
`src/dashboard_store.py` (same import trick as `plugin_api.py`), so the mock
always matches the plugin. Toggle state is persisted only to `state.json` —
the real `~/.hermes/config.yaml` is never touched.

## Theme picker (preview real dashboard themes)

The banner has a **Theme** select with two kinds of entries:

- `Mock light (zinc) — built-in` — the inline tokens in `index.html` (the original
  mock look); selecting it removes any injected theme overrides.
- every `mock/*.yaml` — a real Hermes dashboard theme (e.g. `nord.yaml`), compiled
  by `mock/themes.py` and injected exactly like the host does: `--color-*` tokens
  from `palette`/`colorOverrides`, `--component-*` from `componentStyles`,
  typography/layout rules, the raw `customCSS` block, and the `fontUrl` `<link>`.

The choice persists in `localStorage` (`nc-mock-theme`), and `?theme=nord` in the
URL deep-links a theme (it wins over the saved one), so headless screenshots work:

```
CHROME=.omp/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome
$CHROME --headless=new --no-sandbox --disable-gpu --window-size=1440,2400 \
  --screenshot=/tmp/nord.png --virtual-time-budget=6000 "http://127.0.0.1:8787/?theme=nord"
```

New routes (mock-only, not part of the plugin wire contract):

- `GET /themes` → `{"themes": [{name, label, description, fontUrl, builtin}]}`
- `GET /themes/<name>.css` → compiled theme stylesheet (`__default__` → empty sheet)

Drop any `~/.hermes/dashboard-themes/*.yaml` into `mock/` to preview it. The mock
also models the host DS `@layer base` code-chip rule and the `<Backdrop/>`
vignette/grain (driven by `palette.warmGlow` / `palette.noiseOpacity`), so a
theme's `customCSS` interacts with them the same way as in the real host.

Gotcha the mock reproduces faithfully: for **user** themes the host derives the
shadcn base tokens from the palette *layers* (`--background` / `--midground` /
`--foreground`, alpha applied; bootstrap also sets `--background-base` /
`--midground-base` with alpha dropped), and `--color-foreground` resolves
through the **foreground** layer. A theme with `foreground` at alpha 0 (the
default "invisible overlay") therefore gets a transparent `--color-foreground`
on the live host — every `var(--color-foreground, …)` text goes invisible.
`mock/nord.yaml` compensates with `!important` pins in `customCSS`
(`--color-foreground: var(--midground) !important`, same for `--selection-bg`),
which beat the inline vars `applyTheme()` writes on `<html>`. If you write a dark
theme with an alpha-0 foreground layer, copy those pins.

## Limitations vs the real host

- The SDK is a small full-rebuild renderer, not real React; hook state is keyed
  by component path (fine for this single page).
- No auth/session token — `fetchJSON` is plain `fetch`.
- Everything is same-origin, so no CORS handling.
