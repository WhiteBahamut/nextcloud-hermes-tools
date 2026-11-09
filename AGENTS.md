# AGENTS.md — nextcloud-hermes-tools

You are working in `nextcloud-hermes-tools`, a Hermes Agent **directory plugin** that
gives the agent 44 `nc_*` tools (files, search, shares, Talk, calendar, tasks, contacts,
notes, activity, tags, trashbin, comments, generic OCS) against one Nextcloud server.
Python 3.10+, MIT.

The repo root **is** the plugin directory: install = `git clone <repo>
~/.hermes/plugins/nextcloud-tools`. Root `__init__.py` is a thin loader that mounts
`src/` as the `nextcloud_tools` package; `plugin.yaml` stays at the root for Hermes
discovery. MUST NOT add `pyproject.toml` / `setup.py` — the repo deliberately has no
packaging config.

**Style:** clear instructions in this file use imperative RFC 2119 keywords — `MUST` /
`MUST NOT` for hard requirements (`NEVER` = `MUST NOT`, `AVOID` = `SHOULD NOT`).

Skills and plans authored for this repo MUST use the same imperative RFC 2119 keywords, and every plan step MUST carry explicit Guidance, Guardrails, and a success Check.

When editing files, re-read first — NEVER guess line numbers or edit anchors; if a multi-part edit is rejected, apply the fixes as separate single edits; if a file gets mangled, rewrite it wholesale.

## Do this first

```bash
python3 -m venv .venv && .venv/bin/pip install -q httpx pytest
.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py   # syntax check
.venv/bin/python -m pytest tests -q                              # full suite
```

MUST run both commands before finishing ANY change. Tests MUST use `httpx.MockTransport`
only — MUST NOT open real sockets. `httpx` is imported lazily so the package imports
with the stdlib alone. There is no linter, formatter, or CI config: MUST match the
surrounding style by hand. Every module MUST start with
`from __future__ import annotations` and MUST use type hints and docstrings.

## Layout

| Path | What |
|---|---|
| `plugin.yaml` | Hermes manifest: `provides_tools` (all 44 `nc_*`), `provides_hooks` (`pre_tool_call`), `config_schema` (settings incl. `disabled_tools`) |
| `__init__.py` | Root loader; exposes `register` / `TOOLSET` from `src/` |
| `src/__init__.py` | `register(ctx)`: iterates tool modules, skips `disabled_tools`, registers each tool with `check_fn=client.configured` + `requires_env=list(client.KNOWN_ENV)`; registers `guardrails.guard` as the `pre_tool_call` hook |
| `src/client.py` | HTTP layer: secret resolution, per-call config, `enc_path`, `redact`, `ok`/`err`, the `@tool` wrapper, cached client + retry, DAV helpers, OCS helper, read-back verification |
| `src/guardrails.py` | `pre_tool_call` hook: READ_ONLY / WRITES / DESTRUCTIVE frozensets + arg-dispatch for `nc_comments` / `nc_ocs`; never raises, fails toward approve |
| `src/compat.py` | Install-time Hermes/Nextcloud version check vs tested ranges; INFO within range, WARNING outside |
| `src/schemas.py` | JSON schemas for every tool via the `_s(description, properties, required)` helper |
| `src/tools_*.py` | One module per area (files, search, shares, talk, cal, contacts, notes, misc); each ends with `TOOLS = [("nc_x", schemas.NC_X, client.tool(_x)), ...]` |
| `src/dav.py` | Multistatus parsing; props matched by local tag name (namespace-prefix agnostic) |
| `src/ical.py`, `src/vcard.py` | Stdlib-only ICS / vCard parsers + builders — no dateutil, no extra deps |
| `src/dashboard_store.py` | Persists per-tool enable/disable to `config.yaml`; reads `plugin.yaml` via regex (no yaml import) so tests can import it |
| `dashboard/` | Dashboard tab: `plugin_api.py` (host-only, fastapi) + `manifest.json` + `dist/index.js` |
| `tests/` | pytest; `conftest.py` loads `src/` via importlib and provides `fake_ctx`, `call`, `nc` (MockTransport recording every request) fixtures + `multistatus` / `ocs_ok` / `ocs_err` helpers |

## Hard rules

- Handlers NEVER raise. Wrap every handler with `@client.tool` and return a JSON string
  via `client.ok(**kw)` / `client.err(msg, **kw)` — `{"ok": true, ...}` or
  `{"ok": false, "error": ...}`.
- Every tool is registered with `check_fn=client.configured`: tools fail closed until
  `NC_SERVER_URL` / `NC_USER` / `NC_APP_PASSWORD` resolve. Settings are read fresh on
  every call via `client.get_config(key, default)`.
- Credentials come from the profile's `.env` via `agent.secret_scope.get_secret_str` —
  NEVER `os.getenv` for secrets. `NC_*` preferred, `TALK_*` per-variable fallback (first
  non-empty wins). Never put secrets in code, config, or output; all error strings go
  through `client.redact()` (strips app password, its base64 + URL-encoded forms, and
  `Authorization` values).
- NEVER send a request with unencoded or traversing paths: build paths with
  `client.enc_path` (encodes every segment) + `files_dav` / `cal_dav` / `book_dav` /
  `abs_url`, and reject `..` segments / leading `/` BEFORE any request.
- Every write MUST be verified by read-back before returning `ok: true`: sha256 for
  content (`put_verified` / `verify_file_content`), `verify_exists`, delete via
  `verify_gone` (404).
- DAV quirks are load-bearing, do not "clean them up": explicit `Depth` on every
  PROPFIND; accept 200 AND 207; MOVE 423 (files_lock) → GET bytes → PUT destination →
  DELETE source; HTML-escaped etags must be unescaped before `If-Match`.
- Retry at most once (0.5 s backoff), only for `client.RETRY_SAFE_METHODS`
  (GET/HEAD/OPTIONS/PROPFIND/REPORT), only on connect/read/protocol errors.
- Writes and destructive ops are gated by the `pre_tool_call` hook
  (`hard_block_destructive: true` hard-blocks destructive ops). Classify every new tool in
  `src/guardrails.py`.

## Adding a new `nc_*` tool

See the `nc-add-tool` skill (`.omp/skills/nc-add-tool/SKILL.md`).

## Compatibility checks

See the `nc-compat-hermes` and `nc-compat-nextcloud` skills (`.omp/skills/`) for the regular Hermes/Nextcloud compatibility watchlist.

Compat MUST be verifiable without installing the hosts: check against the pinned git-tag
source — PyPI lags GitHub releases and pip-installing a tag fails on self-referential
extras. For per-version Nextcloud API truth prefer machine-readable sources over the
wiki: the app-store platform API (`apps.nextcloud.com/api/v1/platform/<ver>/apps.json`),
per-major docs branches, GitHub changelog assets, app docs at raw tags; live truth via
`/status.php` + `cloud/capabilities`.

## Offline validation

API-validation scripts MUST be offline and deterministic: committed pinned upstream
bytes with a sha256 lock (`upstream_pins.json` / `upstream_lock.json`) under the owning
agent's `.omp/agents/<name>/scripts/`; only caches and scratch venvs are git-ignored.
The releases-feed pin is the deliberate tripwire — it MUST FAIL loudly when upstream
publishes a new release.

## Git

Conventional commits — `feat:` / `fix:` / `perf:` / `security:` / `docs:` + short
description (see `git log`). One logical change per PR.

Before committing changes to `src/`, MUST run the `nc-tool-review` and
`nc-security-audit` subagents (via the `task` tool).

**Version bump is mandatory:** every commit MUST also bump `version:` in
`plugin.yaml` (line 2) so Hermes sees the new version after `git pull`.
Semver mapped from the conventional-commit type: `fix:` / `perf:` /
`security:` / `docs:` → patch, `feat:` → minor, breaking change (`!` suffix
or `BREAKING CHANGE` footer) → major. The `dashboard/manifest.json` version
is the dashboard tab's own version, not the plugin version — do not sync it.

## Never

- MUST NOT add new third-party dependencies (runtime: `httpx` only; tests: `pytest` only).
- MUST NOT use curl/shell workarounds for Nextcloud APIs — everything MUST go through `src/client.py`.
- MUST NOT make real network calls in tests; MUST NOT change the Hermes host itself.
- `dashboard/plugin_api.py` is host-only (fastapi) — MUST NOT be imported from the CLI
  plugin or tests; MUST keep its wire contract with `dist/index.js` (`GET /tools`, `PUT /tools/{name}`) in sync on both sides.
