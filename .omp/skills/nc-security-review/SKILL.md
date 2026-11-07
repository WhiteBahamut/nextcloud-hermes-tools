---
name: nc-security-review
description: Security invariant checklist for reviewing changes in nextcloud-hermes-tools (secrets, path encoding, redaction, read-back, retries, guardrails, tests)
---

# Security invariant checklist

Base invariants: `AGENTS.md` → "Hard rules" + "Never" (tests: "Do this first") — source of truth.
Run each check below on the diff:

## Secrets & output
- MUST grep diff for `password|secret|token|app_password|Authorization` — no secrets in code, tests, fixtures, config, logs, output
- credentials MUST come only from `agent.secret_scope.get_secret_str` (profile `.env`) — MUST NOT use `os.getenv`
- every error string MUST go through `client.redact()`; any new secret format MUST be stripped by it + have a test

## Requests & paths
- paths MUST be built with `client.enc_path` + `files_dav`/`cal_dav`/`book_dav`/`abs_url` — no raw user input in URLs
- `..` and leading `/` MUST be rejected before any request; tests MUST assert no request was sent
- no phone-home: all HTTP MUST go via the cached `httpx.Client` in `client.get_client()` (`base_url` = configured server only); grep diff for `http://`/`https://` literals and network use outside `src/client.py` — none allowed; no telemetry/analytics/DNS; `follow_redirects` MUST stay off
- retries MUST be at most once (0.5 s), only `client.RETRY_SAFE_METHODS`, only connect/read/protocol errors
- DAV quirks MUST stay: explicit `Depth` per PROPFIND; accept 200 AND 207; MOVE 423 → GET → PUT → DELETE; HTML-unescape etags before `If-Match`

## Code shape & wiring
- handlers MUST be `@client.tool`-wrapped, return `client.ok`/`client.err` JSON, MUST NOT raise; new tools MUST use `check_fn=client.configured` + `requires_env`
- every write MUST be read-back verified (`put_verified`/`verify_exists`/`verify_gone`); mismatch test MUST return `ok: false`
- new tool MUST be in `schemas.py` + module `TOOLS` + `plugin.yaml` `provides_tools` + a `guardrails.py` class; writes/destructive MUST be gated by `pre_tool_call`
- MUST NOT add deps (runtime `httpx` only, tests `pytest` only); no curl/shell workarounds — all API calls via `src/client.py`
- `dashboard/plugin_api.py` MUST NOT be imported by CLI plugin or tests; wire contract (`GET /tools`, `PUT /tools/{name}`) MUST stay in sync with `dist/index.js`

## Tests & verify
- tests MUST use `httpx.MockTransport` only — no real sockets; MUST assert on `nc.requests`; MUST NOT touch the Hermes host
- `py_compile __init__.py src/*.py tests/*.py` and `pytest tests -q` MUST pass

