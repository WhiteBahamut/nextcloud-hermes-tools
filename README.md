# nextcloud-hermes-tools

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) **directory plugin** that gives the agent first-class **Nextcloud tools** — files, full-text search, shares, Talk rooms, calendar, tasks, contacts, notes, activity and more — as real tool calls with schemas, instead of shelling out to curl.

All 43 tools live in the `nextcloud` toolset. Every handler returns a JSON string and never raises; every write is verified by read-back; a `pre_tool_call` hook gates writes/destructive ops through the approval system.

## Table of Contents

- [nextcloud-hermes-tools](#nextcloud-hermes-tools)
  - [Table of Contents](#table-of-contents)
  - [Requirements](#requirements)
  - [Tools](#tools)
  - [Install](#install)
  - [Usage](#usage)
  - [Configuration](#configuration)
  - [Security](#security)
  - [Development](#development)
  - [Contributing](#contributing)
  - [Support](#support)
  - [License](#license)

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed and running
- Python 3.10+ (Hermes host provides this)
- `httpx` (core Hermes dependency, always present in-host)
- A Nextcloud instance with an app password for the bot account

## Tools

| Tool | API | Notes |
|---|---|---|
| `nc_file_list` / `nc_file_get` / `nc_file_put` / `nc_file_mkdir` / `nc_file_move` / `nc_file_delete` | WebDAV `/remote.php/dav/files/<user>/` | Server quirks baked in: explicit `Depth`, accept 200 **and** 207 on PROPFIND, URL-encoded paths, MOVE 423 (`files_lock`) → GET bytes → PUT → DELETE fallback, read-back verification after every write, delete verified 404 |
| `nc_search` | OCS `/ocs/v2.php/search/providers/<id>/search` | Cross-app: `files`, `fulltextsearch` (matches **inside** file content), `talk-message`, `calendar`, `tasks`, `contacts`, `notes`, …; a missing provider is a per-provider error, never a failed call |
| `nc_file_search` | PROPFIND `Depth: infinity` + local filter | Fallback; server-side DAV `SEARCH` is NotImplemented |
| `nc_share_list` / `nc_share_create` / `nc_share_delete` | OCS files_sharing API | `shareType=0`, `permissions=31`; create verified via GET read-back |
| `nc_talk_rooms` / `nc_talk_messages` / `nc_talk_send` / `nc_talk_delete` / `nc_talk_react` | Talk OCS v4 | DMs filtered (settings `talk_include_dms`, `talk_skip_tokens`), chat always `lookIntoFuture=0`, send verified by chat read-back |
| `nc_cal_list` / `nc_cal_create` / `nc_cal_edit` / `nc_cal_delete` | CalDAV REPORT time-range + PUT/DELETE `If-Match` | Client-side RRULE expansion (cap 500), all-day `VALUE=DATE`, etags arrive HTML-escaped → unescaped before `If-Match`; shared calendars addressed by DAV dir `<name>_shared_by_<Owner>` |
| `nc_task_list` / `nc_task_create` / `nc_task_complete` | VTODO via CalDAV | `NEEDS-ACTION`/`COMPLETED`; completion sets `STATUS:COMPLETED` + `COMPLETED` timestamp |
| `nc_contact_list` / `nc_contact_search` / `nc_contact_get` / `nc_contact_create` / `nc_contact_edit` | CardDAV | CDATA stripping, vCard line unfolding, vCard 4.0 writes |
| `nc_note_list` / `nc_note_get` / `nc_note_create` / `nc_note_edit` / `nc_note_delete` | `/index.php/apps/notes/api/v1/notes` | OCS path 998s on some servers → verified WebDAV `Notes/` fallback (title ↔ `<title>.txt`) |
| `nc_activity` / `nc_notifications` | activity / notifications APIs | Bot account's own feed |
| `nc_tag_list` / `nc_tag_assign` / `nc_tag_unassign` | systemtags DAV | PROPPATCH `oc:systemtags` + verified read-back |
| `nc_trash_list` / `nc_trash_restore` / `nc_trash_empty` | trashbin DAV | Restore = MOVE to original location with `Overwrite: F` |
| `nc_comments` | comments DAV | `action=list` read-only; `add` write-gated; `delete` destructive; `path` resolved to `oc:fileid` |
| `nc_ocs` | generic OCS v2 escape hatch | Traversal (`..`, leading `/`) rejected before any request |

## Install

The repo root **is** the plugin directory — clone it into one profile's plugins dir. Source files live in `src/`; the root `__init__.py` is a thin loader that mounts `src/` as the `nextcloud_tools` package, and `plugin.yaml` stays at the root for Hermes discovery.

```bash
git clone <this-repo-url> ~/.hermes/plugins/nextcloud-tools
hermes plugins doctor nextcloud-tools   # validate discovery + registration
hermes plugins enable nextcloud-tools   # enabling the plugin turns the "nextcloud" toolset on by default
# or in config.yaml: plugins.enabled: ["nextcloud-tools"]
```

No separate toolset step is required: once the plugin is in `plugins.enabled`, the
`nextcloud` toolset is on by default (upstream `_enabled_plugin_toolsets`). Contingency:
if the profile has a saved tool selection (`platform_toolsets.<platform>`, written by
`hermes tools`) in which `nextcloud` was unchecked, re-check it in `hermes tools` —
enabling the plugin via the CLI re-adds it automatically.

Profile isolation comes from placement: one copy per profile's `~/.hermes/plugins/`, each profile with its own `NC_*` (or `TALK_*`) in its own `.env`.

## Usage

Once enabled, the agent calls tools directly — no curl, no shell:

```
nc_file_list(path="/Documents")
nc_search(query="quarterly report", providers=["files", "fulltextsearch"])
nc_talk_send(token="abc123", message="Standup moved to 10:00")
nc_cal_create(summary="Dentist", start="2026-11-10T14:00:00", end="2026-11-10T15:00:00")
nc_note_create(title="Ideas", content="...")
```

Every call returns a JSON string. Read-only calls pass through the normal approval policy; writes and destructive ops go through the approval gate (see [Security](#security)).

## Configuration

Credentials come from the active profile's `.env`. `NC_*` variables are
preferred; the `TALK_*` names (same as the Talk platform plugin) work as a
fallback — each variable resolves independently, first non-empty wins:

```bash
NC_SERVER_URL=https://cloud.example.com
NC_USER=Hermes            # bot account per profile
NC_APP_PASSWORD=...       # app password, never the login password
# TALK_SERVER_URL / TALK_USER / TALK_APP_PASSWORD also accepted (fallback)
```

Optional plugin settings (`plugins.entries.nextcloud-tools.settings.<key>`):

```yaml
ca_bundle: ""            # PEM path for an internal CA; empty = system CAs
default_search_providers: ["files", "fulltextsearch", "talk-message", "calendar", "tasks"]
max_results: 20
request_timeout: 30.0
talk_include_dms: false  # include 1:1 DM rooms in nc_talk_rooms
talk_skip_tokens: []     # room tokens always excluded (gateway-polled DM)
hard_block_destructive: false  # true = hard-block destructive ops instead of approval gate
```

## Security

- App password only (revocable per app in Nextcloud → Settings → Security); stored in the profile's `.env`, never in config or code.
- Profile-scoped secret reads via `agent.secret_scope.get_secret_str` — one profile's token can never be used by another; never `os.getenv`.
- Read-only `nc_*` tools pass through the normal approval policy; **writes** are routed to the approval gate and **destructive** ops (delete, share-delete, trash-empty, comment-delete) additionally require explicit confirmation — or are hard-blocked with `hard_block_destructive: true`. The hook fails closed: any internal error blocks the call.
- All writes verified by read-back (sha256 for content, PROPFIND/GET for existence) before `ok: true` is returned.
- No secrets in output: the client redacts the app password, `base64(user:password)` and `Authorization` header values from every error string.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -q httpx pytest
.venv/bin/python -m py_compile __init__.py src/*.py tests/*.py
.venv/bin/python -m pytest tests -q
```

Tests use `httpx.MockTransport` only — no real sockets. `httpx` itself is imported lazily, so the package imports with the stdlib alone; in the Hermes host it is a core dependency.

## Contributing

Contributions welcome. Please:

1. Fork the repo and create a feature branch (`git checkout -b feat/my-change`).
2. Keep changes scoped — one logical change per PR.
3. Run the test suite before submitting: `.venv/bin/python -m pytest tests -q`.
4. Open a PR with a clear description of what changed and why.

Bug reports and feature requests: please use [GitHub Issues](../../issues).

## Support

- **Issues / bugs:** [GitHub Issues](../../issues)
- **Hermes Agent questions:** [Hermes Agent repo](https://github.com/NousResearch/hermes-agent)

## License

[MIT](LICENSE)
