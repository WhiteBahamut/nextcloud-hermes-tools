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

## Limitations vs the real host

- The SDK is a small full-rebuild renderer, not real React; hook state is keyed
  by component path (fine for this single page). Tabs keeps its active tab in a
  module-level store so conditional siblings can't remount it.
- No auth/session token — `fetchJSON` is plain `fetch`.
- Everything is same-origin, so no CORS handling.
