---
name: nc-compat-nextcloud
description: Check the nc_* tools against a Nextcloud server — run after every server upgrade: support-version floor, release-note deprecation sweep, per-version OCS doc diff, app API versions (Talk v4, Notes v1, search providers), live smoke via the tools themselves, repo checks; records the checked-against server version in last-checked.json
---

# Checking Nextcloud compatibility

Run top-to-bottom after every Nextcloud server upgrade (majors land ~every 4 months) and
before any release. The endpoint inventory below is what the plugin actually calls —
verified in `src/client.py`, `src/tools_*.py`. The checked-against server version is
recorded in `.omp/skills/nc-compat-nextcloud/last-checked.json` at the end (step 10) and
reported at the start of the next run (step 1).
Endpoint inventory:
- WebDAV: `/remote.php/dav/files/<user>/` (`src/client.py:171`),
  `/remote.php/dav/calendars/<user>/…` and `/addressbooks/users/<user>/…` (`src/client.py:177,186`),
  `/remote.php/dav/systemtags/`, `/trashbin/<user>/trash/`, `/comments/files/<fileId>`
  (`src/tools_misc.py:64,110,211`)
- OCS v2 with header `OCS-APIRequest: true` (`src/client.py:305,415`):
  `apps/files_sharing/api/v1/shares` (`tools_shares.py:13`),
  `apps/spreed/api/v4/room…` (`tools_talk.py:17`),
  `apps/notifications/api/v2/notifications` (`tools_misc.py:55`),
  `search/providers/<id>/search` (`tools_search.py:29`)
- index.php apps: `/index.php/apps/activity/api/v2/activity` (`tools_misc.py:40`),
  `/index.php/apps/notes/api/v1/notes` (`tools_notes.py:16`)
- Auth: Basic auth `user:app-password` (app passwords / Login Flow v2);
  `OC-Checksum: SHA256:…` on PUT with read-back verification (`src/client.py:465-473`)
- Load-bearing DAV quirks: explicit `Depth`, 200 AND 207 accepted, MOVE 423
  (files_lock) fallback, HTML-escaped etags (`src/client.py:377-380`)

1. **Report the last recorded check.** Read
   `.omp/skills/nc-compat-nextcloud/last-checked.json` if it exists and state its
   `target_version`, `checked_at`, and `result`.
   - Guardrail: a missing or corrupt file means "never checked" — report that and
     continue; do not fail, do not guess.
2. **Pin the support floor and the server version.** Read the "Currently supported
   versions" table in the nextcloud/server wiki "Maintenance and Release Schedule"
   (https://github.com/nextcloud/server/wiki/Maintenance-and-Release-Schedule; mirror:
   docs.nextcloud.com/server/stable/admin_manual/release_schedule.html). Rule: new major
   ~every 4 months, each supported 1 year. The oldest listed major is the compat floor.
   Get the live server's version from `/status.php` (`status.version`, e.g. `36.0.2`)
   and via `nc_ocs GET cloud/capabilities`; it must be >= floor. Save the server
   version string — it becomes `target_version` in step 10.
   - Guidance: read the table at check time — never hardcode a floor (as of 2026-11 the
     docs site shows NC 36 latest / NC 35 stable).
   - Guardrail: if the server is below the floor, that is an upgrade-the-server finding,
     not a code change.
3. **Check for a newer server major.** Re-read the maintenance/release schedule
   table (same source as step 2) for the newest released major and the oldest
   supported major (floor); compare both against `NC_TESTED_MAJOR_MIN` /
   `NC_TESTED_MAJOR_MAX` in `src/compat.py`.
   - If the live `/status.php` major or the newest released major exceeds
     `NC_TESTED_MAJOR_MAX`: sweep steps 4–7 for that major and ONLY on final
     result `pass` set `NC_TESTED_MAJOR_MAX` in `src/compat.py` to the highest
     verified major and `NC_TESTED_MAJOR_MIN` to the wiki floor read at check
     time; record via step 10.
   - On `fail` the constants stay unchanged; name the reason in `notes`.
4. **Release-notes sweep.** For each major from floor to the server's version, read
   https://github.com/nextcloud/server/releases and nextcloud.com/changelog and grep for
   `deprecated`/`removed` hitting the inventory above.
   - Guardrail: OCS app APIs are versioned (`api/v1`, `v2`, `v4`); an old version is only
     removed when the app ships a new one (Talk removed v1–v3 with v4 at NC 21) — a
     version bump in the notes is a breaking change for us.
5. **Diff the per-version OCS overview** between floor and latest:
   https://docs.nextcloud.com/server/<v>/developer_manual/client_apis/OCS/ocs-api-overview.html
6. **Check app API docs.**
   - Talk: https://nextcloud-talk.readthedocs.io/en/latest/ — we pin `api/v4`
     (`tools_talk.py:17`); watch for a v5. Talk version is in `cloud/capabilities`.
   - Notes: `/index.php/apps/notes/api/v1/notes` — watch for v2.
   - Search providers: enumerate `GET /ocs/v2.php/search/providers` and compare IDs with
     `default_search_providers` in `plugin.yaml` (`files`, `fulltextsearch`,
     `talk-message`, `calendar`, `tasks`); fulltextsearch is an app-store app — check its
     `info.xml` NC min/max after server or app upgrades.
7. **Live smoke through the tools themselves** (agent running against the real server):
   `nc_ocs GET cloud/capabilities`, then one read per family — `nc_file_list`,
   `nc_search`, `nc_file_search`, `nc_share_list`, `nc_talk_rooms`, `nc_talk_messages`,
   `nc_cal_list`, `nc_task_list`, `nc_contact_list`, `nc_contact_search`, `nc_note_list`,
   `nc_activity`, `nc_notifications`, `nc_tag_list`, `nc_trash_list`, `nc_comments`
   (`action=list`). Any successful call also proves Basic-auth app-password still works.
   - Guardrails: tests stay hermetic (`httpx.MockTransport`, no real sockets — AGENTS.md);
     live checks go through the running agent's tools or a throwaway script using
     `src/client` with real profile env, never as committed tests. MUST NOT guess an
     endpoint from memory when re-checking — look it up in the official docs and record
     the exact endpoint (same rule as the `nc-add-tool` skill).
8. **On any family failure:** first re-check steps 4–6 for an API version bump before
   changing code; record the exact endpoint + server version in the issue; fix following
   the `nc-add-tool` runbook (schema, handler, TOOLS, plugin.yaml, guardrails, tests,
   version bump).
9. **Repo checks.** `.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py`
   and `.venv/bin/python -m pytest tests -q` — MUST pass.
10. **Record this check.** Write `.omp/skills/nc-compat-nextcloud/last-checked.json` as a
   single JSON object with exactly these five keys (example):
   ```json
   {"skill": "nc-compat-nextcloud", "checked_at": "2026-11-07",
    "target_version": "36.0.2", "result": "pass", "notes": ""}
   ```
   `checked_at` = today's date (`YYYY-MM-DD`); `target_version` = the server version
   string from step 2 (`/status.php` `status.version`); `result` = `"pass"` only if
   steps 2–9 all passed, else `"fail"`; `notes` = one line naming any broken family or
   API version bump found (may be empty).
   - Guardrails: write the file last, after all checks; exactly five keys, no extras;
     never hand-edit it between runs; the file stays untracked via the `.gitignore`
     line `.omp/skills/*/last-checked.json` — MUST NOT be committed; on `pass`,
     `NC_TESTED_MAJOR_MIN` in `src/compat.py` MUST equal the schedule floor read at
     check time and the `target_version` major MUST be <= `NC_TESTED_MAJOR_MAX`.
