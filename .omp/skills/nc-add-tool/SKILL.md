---
name: nc-add-tool
description: Runbook for adding a new nc_* tool to nextcloud-hermes-tools (schema, handler, TOOLS, plugin.yaml, guardrails, tests, version bump)
---

# Adding a new `nc_*` tool

This skill is the source of truth for this runbook; `AGENTS.md` → "Adding a new `nc_*` tool"
points here. MUST NOT duplicate the runbook in `AGENTS.md`.

1. **Research the Nextcloud API first.** MUST look the feature up in the official Nextcloud
   developer documentation (Server Developer Manual + the relevant app's OCS/REST API
   reference) and MUST confirm against the target server version: HTTP method, exact path
   (WebDAV `/remote.php/dav/...` or OCS `/ocs/v2.php/...`), request params/body, response
   shape (incl. the OCS `{"ocs": {"meta", "data"}}` envelope), and server quirks. MUST NOT
   guess an endpoint from memory. MUST record the exact endpoint in the new `src/tools_*.py`
   module docstring — every existing module does this (e.g. `tools_talk.py:1` cites the
   OCS `/ocs/v2.php/apps/spreed/api/v4/` base).
2. **Schema.** MUST add its JSON schema in `src/schemas.py` using
   `_s(description, properties, required)`.
3. **Handler.** MUST implement it in the matching `src/tools_*.py`, wrapped with
   `client.tool(...)`.
4. **Register.** MUST append `("nc_new", schemas.NC_NEW, client.tool(_new))` to that module's
   `TOOLS` list.
5. **Manifest.** MUST add `nc_new` to `provides_tools` in `plugin.yaml`.
6. **Guardrails.** MUST classify it in `src/guardrails.py` — READ_ONLY / WRITES / DESTRUCTIVE
   frozenset, or the arg-dispatch branch when classification depends on args (like
   `nc_comments` / `nc_ocs`).
7. **Tests.** MUST add tests in `tests/test_<area>.py` using the `nc` + `call` fixtures from
   `tests/conftest.py`; MUST also assert on `nc.requests`. For a write, MUST also test the
   read-back verification path including the mismatch case.
8. **Verify.** MUST run the commands under `AGENTS.md` → "Do this first"; MUST keep one
   logical change per PR.

Commit + version bump afterwards: see the `nc-commit` skill.
