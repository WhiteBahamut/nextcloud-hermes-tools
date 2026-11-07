"""JSON-Schema definitions for all 43 nextcloud-tools.

One dict per tool: ``{"description": ..., "parameters": {"type": "object", ...}}``.
Descriptions teach the model when to call each tool.
"""


def _s(description, properties, required=()):
    return {
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)},
    }


PATH = {"type": "string", "description": "Server-side path, e.g. '/Documents/report.pdf'."}
CAL = {
    "type": "string",
    "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
}
BOOK = {"type": "string", "description": "Address book DAV directory name."}

# --- files (WebDAV) ----------------------------------------------------------

NC_FILE_LIST = _s(
    "List entries of a Nextcloud folder (WebDAV PROPFIND). depth '0' = the entry itself, '1' = direct children (default), 'infinity' = whole subtree (cap with limit).",
    {
        "path": {**PATH, "default": "/"},
        "depth": {"type": "string", "enum": ["0", "1", "infinity"], "default": "1"},
        "limit": {"type": "integer", "default": 200, "description": "Max entries returned."},
    },
)
NC_FILE_GET = _s(
    "Download a file. utf-8-decodable content comes back as `content`, binary as `content_base64` (unless raw=true, which forces base64).",
    {
        "path": PATH,
        "raw": {"type": "boolean", "default": False, "description": "Force base64 even for text."},
    },
    ["path"],
)
NC_FILE_PUT = _s(
    "Create or overwrite a file (PUT + read-back sha256 verification). Use `content` for text, `content_base64` for binary (wins over content).",
    {
        "path": PATH,
        "content": {"type": "string", "default": "", "description": "Text content (utf-8)."},
        "content_base64": {"type": "string", "default": "", "description": "Base64-encoded binary content."},
        "content_type": {"type": "string", "default": "", "description": "Optional Content-Type header."},
    },
    ["path"],
)
NC_FILE_MKDIR = _s(
    "Create a folder (MKCOL), verified by PROPFIND read-back.",
    {"path": PATH},
    ["path"],
)
NC_FILE_MOVE = _s(
    "Move or rename a file/folder (WebDAV MOVE; on 423 files_lock falls back to GET bytes -> PUT destination -> DELETE source). `destination` is the new FULL path, not a folder. Verified.",
    {
        "source": {**PATH, "description": "Current path."},
        "destination": {**PATH, "description": "New full path."},
        "overwrite": {"type": "boolean", "default": True},
    },
    ["source", "destination"],
)
NC_FILE_DELETE = _s(
    "Delete a file or folder (goes to the trashbin). DESTRUCTIVE — gated by the pre_tool_call hook; verified 404 afterwards.",
    {"path": PATH},
    ["path"],
)

# --- search ------------------------------------------------------------------

NC_SEARCH = _s(
    "Unified cross-app search (OCS search providers): files, fulltextsearch (matches INSIDE file content), talk-message, calendar, tasks, contacts, notes, ... A provider not installed on the server is reported as a per-provider error, never fails the whole call.",
    {
        "term": {"type": "string", "description": "Search term."},
        "providers": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Provider ids; empty = settings default_search_providers.",
        },
        "limit": {"type": "integer", "default": 0, "description": "Per-provider limit; 0 = settings max_results."},
    },
    ["term"],
)
NC_FILE_SEARCH = _s(
    "Filename search inside a folder subtree (PROPFIND Depth infinity + local case-insensitive filter; server-side DAV SEARCH is not implemented).",
    {
        "term": {"type": "string"},
        "path": {**PATH, "default": "/"},
        "limit": {"type": "integer", "default": 100},
    },
    ["term"],
)

# --- shares ------------------------------------------------------------------

NC_SHARE_LIST = _s(
    "List shares, optionally filtered to one path. shareType 0 = user/group share, 3 = public link.",
    {"path": {**PATH, "default": ""}},
)
NC_SHARE_CREATE = _s(
    "Create a share (default: user/group share, permissions 1 = read-only). Verified by read-back. Gated by the approval hook.",
    {
        "path": PATH,
        "share_with": {"type": "string", "description": "User or group name (shareType 0)."},
        "share_type": {"type": "integer", "default": 0, "description": "0 = user/group, 3 = public link."},
        "permissions": {"type": "integer", "default": 1, "description": "Permission bitmask; 1 = read-only (default), 31 = all — pass explicitly."},
        "note": {"type": "string", "default": ""},
    },
    ["path", "share_with"],
)
NC_SHARE_DELETE = _s(
    "Delete a share by id. DESTRUCTIVE — gated; verified 404 afterwards.",
    {"id": {"type": "integer"}},
    ["id"],
)

# --- talk --------------------------------------------------------------------

NC_TALK_ROOMS = _s(
    "List Talk rooms. 1:1 DMs are excluded unless settings talk_include_dms; tokens listed in talk_skip_tokens are always dropped (e.g. the gateway-polled DM — never double-handle).",
    {"limit": {"type": "integer", "default": 50}},
)
NC_TALK_MESSAGES = _s(
    "Read recent messages of a room (always sent with lookIntoFuture=0 — the gateway polls DMs separately). Paginate with last_known_message_id.",
    {
        "token": {"type": "string", "description": "Room token."},
        "limit": {"type": "integer", "default": 50},
        "last_known_message_id": {"type": "integer", "default": 0, "description": "Only messages after this id."},
    },
    ["token"],
)
NC_TALK_SEND = _s(
    "Send a message to a Talk room; verified by chat read-back containing the new message id. Gated by the approval hook.",
    {
        "token": {"type": "string"},
        "message": {"type": "string"},
        "reply_to": {"type": "integer", "default": 0, "description": "Message id to reply to; 0 = top-level."},
    },
    ["token", "message"],
)
NC_TALK_DELETE = _s(
    "Delete a Talk message. DESTRUCTIVE — gated.",
    {"token": {"type": "string"}, "message_id": {"type": "integer"}},
    ["token", "message_id"],
)
NC_TALK_REACT = _s(
    "Add (react=true) or remove (react=false) an emoji reaction on a message. Writes are gated.",
    {
        "token": {"type": "string"},
        "message_id": {"type": "integer"},
        "emoji": {"type": "string"},
        "react": {"type": "boolean", "default": True},
    },
    ["token", "message_id", "emoji"],
)

# --- calendar + tasks ----------------------------------------------------------

NC_CAL_LIST = _s(
    "List calendar events in a time range (CalDAV REPORT time-range; recurring events expanded client-side, capped at 500 occurrences). Defaults: from = now-30d, to = now+90d.",
    {
        "calendar": {**CAL, "default": "personal"},
        "from": {"type": "string", "default": "", "description": "ISO 8601 range start, e.g. 2026-11-01T00:00:00+00:00."},
        "to": {"type": "string", "default": "", "description": "ISO 8601 range end."},
        "limit": {"type": "integer", "default": 100},
    },
)
NC_CAL_CREATE = _s(
    "Create a calendar event (PUT new .ics, verified read-back). Gated. start/end ISO 8601 (or YYYY-MM-DD when all_day). rrule e.g. 'FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10'.",
    {
        "calendar": {**CAL, "default": "personal"},
        "summary": {"type": "string"},
        "start": {"type": "string", "description": "ISO 8601 start, or YYYY-MM-DD when all_day."},
        "end": {"type": "string", "description": "ISO 8601 end, or YYYY-MM-DD when all_day."},
        "all_day": {"type": "boolean", "default": False},
        "description": {"type": "string", "default": ""},
        "location": {"type": "string", "default": ""},
        "rrule": {"type": "string", "default": "", "description": "e.g. FREQ=DAILY;INTERVAL=2;COUNT=5 or FREQ=WEEKLY;BYDAY=MO,FR;UNTIL=20261231"},
    },
    ["summary", "start", "end"],
)
NC_CAL_EDIT = _s(
    "Edit an existing event by UID (href+etag resolved via REPORT, PUT with If-Match, verified read-back). Only provided fields are changed. Gated.",
    {
        "calendar": CAL,
        "uid": {"type": "string", "description": "VEVENT UID."},
        "summary": {"type": "string", "default": ""},
        "start": {"type": "string", "default": ""},
        "end": {"type": "string", "default": ""},
        "all_day": {"type": "boolean", "default": False},
        "description": {"type": "string", "default": ""},
        "location": {"type": "string", "default": ""},
        "rrule": {"type": "string", "default": ""},
    },
    ["calendar", "uid"],
)
NC_CAL_DELETE = _s(
    "Delete a calendar event by UID (DELETE with If-Match). DESTRUCTIVE — gated.",
    {"calendar": CAL, "uid": {"type": "string"}},
    ["calendar", "uid"],
)
NC_TASK_LIST = _s(
    "List tasks (VTODO) of a calendar (default 'tasks'). include_completed=true also returns COMPLETED tasks.",
    {
        "calendar": {**CAL, "default": "tasks"},
        "include_completed": {"type": "boolean", "default": False},
        "limit": {"type": "integer", "default": 200},
    },
)
NC_TASK_CREATE = _s(
    "Create a task (VTODO, STATUS:NEEDS-ACTION; PUT + verified read-back). Gated.",
    {
        "calendar": {**CAL, "default": "tasks"},
        "summary": {"type": "string"},
        "due": {"type": "string", "default": "", "description": "ISO 8601 or YYYY-MM-DD; empty = no due date."},
        "priority": {"type": "integer", "default": 0, "description": "1 = highest ... 9 = lowest; 0 = none."},
        "description": {"type": "string", "default": ""},
    },
    ["summary"],
)
NC_TASK_COMPLETE = _s(
    "Mark a task COMPLETED (sets STATUS:COMPLETED + COMPLETED timestamp, PUT If-Match, verified). Gated.",
    {"calendar": {**CAL, "default": "tasks"}, "uid": {"type": "string"}},
    ["uid"],
)

# --- contacts ------------------------------------------------------------------

NC_CONTACT_LIST = _s(
    "List contacts of an address book (CardDAV PROPFIND Depth 1; default book 'contacts').",
    {"book": {**BOOK, "default": "contacts"}, "limit": {"type": "integer", "default": 500}},
)
NC_CONTACT_SEARCH = _s(
    "Search contacts by substring over name/email/phone (case-insensitive local filter on the parsed book).",
    {"book": {**BOOK, "default": "contacts"}, "term": {"type": "string"}},
    ["term"],
)
NC_CONTACT_GET = _s(
    "Get one contact by UID (fn, emails, phones, org, note).",
    {"book": {**BOOK, "default": "contacts"}, "uid": {"type": "string"}},
    ["uid"],
)
NC_CONTACT_CREATE = _s(
    "Create a contact (vCard 4.0 with FN + UID, PUT + verified read-back). Gated.",
    {
        "book": {**BOOK, "default": "contacts"},
        "fn": {"type": "string", "description": "Full name (required by vCard)."},
        "email": {"type": "string", "default": ""},
        "phone": {"type": "string", "default": ""},
        "org": {"type": "string", "default": ""},
        "note": {"type": "string", "default": ""},
    },
    ["fn"],
)
NC_CONTACT_EDIT = _s(
    "Edit a contact by UID (GET, modify provided fields, PUT with If-Match, verified). Gated.",
    {
        "book": {**BOOK, "default": "contacts"},
        "uid": {"type": "string"},
        "fn": {"type": "string", "default": ""},
        "email": {"type": "string", "default": ""},
        "phone": {"type": "string", "default": ""},
        "org": {"type": "string", "default": ""},
        "note": {"type": "string", "default": ""},
    },
    ["uid"],
)

# --- notes ---------------------------------------------------------------------

NC_NOTE_LIST = _s(
    "List notes (Notes app API; falls back to the WebDAV 'Notes/' folder when the API is unavailable). API content is truncated to a 200-char preview; DAV content is only fetched with with_content=true (default false = metadata only).",
    {
        "category": {"type": "string", "default": ""},
        "limit": {"type": "integer", "default": 50, "description": "Max notes returned."},
        "with_content": {"type": "boolean", "default": False, "description": "DAV fallback: include a 200-char content preview per note (costs one GET per note)."},
    },
)
NC_NOTE_GET = _s(
    "Get one full note by id (Notes API id, or title via the WebDAV fallback).",
    {"id": {"type": "string", "description": "Note id (API) or title (DAV fallback)."}},
    ["id"],
)
NC_NOTE_CREATE = _s(
    "Create a note. Gated; verified by read-back.",
    {
        "title": {"type": "string"},
        "content": {"type": "string", "default": ""},
        "category": {"type": "string", "default": ""},
    },
    ["title"],
)
NC_NOTE_EDIT = _s(
    "Edit note content and/or title. Gated; verified by read-back.",
    {"id": {"type": "string"}, "content": {"type": "string", "default": ""}, "title": {"type": "string", "default": ""}},
    ["id"],
)
NC_NOTE_DELETE = _s(
    "Delete a note. DESTRUCTIVE — gated.",
    {"id": {"type": "string"}},
    ["id"],
)

# --- misc ----------------------------------------------------------------------

NC_ACTIVITY = _s(
    "Recent activity of the bot account (file/calendar actions).",
    {
        "limit": {"type": "integer", "default": 50},
        "since": {"type": "integer", "default": 0, "description": "Unix timestamp; only newer entries."},
    },
)
NC_NOTIFICATIONS = _s(
    "Pending OCS notifications of the bot account itself.",
    {"limit": {"type": "integer", "default": 50}},
)
NC_TAG_LIST = _s("List all system tags.", {})
NC_TAG_ASSIGN = _s(
    "Assign a system tag to a file/folder (PROPPATCH oc:systemtags + verified PROPFIND read-back). Gated.",
    {"path": PATH, "tag": {"type": "string", "description": "Tag name (see nc_tag_list)."}},
    ["path", "tag"],
)
NC_TAG_UNASSIGN = _s(
    "Remove a system tag from a file/folder (PROPPATCH + verified read-back). Gated.",
    {"path": PATH, "tag": {"type": "string"}},
    ["path", "tag"],
)
NC_TRASH_LIST = _s(
    "List trashbin entries (original location, deletion time, size).",
    {"limit": {"type": "integer", "default": 100}},
)
NC_TRASH_RESTORE = _s(
    "Restore a trashbin entry to its original location (MOVE with Overwrite: F, verified). Gated.",
    {"trash_path": {"type": "string", "description": "Trash path as returned by nc_trash_list."}},
    ["trash_path"],
)
NC_TRASH_EMPTY = _s(
    "Empty the ENTIRE trashbin. DESTRUCTIVE — gated (hard-blocked when settings hard_block_destructive=true).",
    {},
)
NC_COMMENTS = _s(
    "File comments (comments DAV). action=list is read-only; add is a gated write; delete is DESTRUCTIVE. Give `file_id` or `path` (path is resolved to oc:fileid via PROPFIND).",
    {
        "action": {"type": "string", "enum": ["list", "add", "delete"], "default": "list"},
        "file_id": {"type": "string", "default": "", "description": "Numeric file id."},
        "path": {**PATH, "default": ""},
        "message": {"type": "string", "default": "", "description": "Comment text (action=add)."},
        "comment_id": {"type": "integer", "default": 0, "description": "Comment id (action=delete)."},
    },
)
NC_OCS = _s(
    "Generic OCS v2 escape hatch for any unmapped endpoint under /ocs/v2.php/. The path must NOT start with '/' and must NOT contain '..' (traversal is rejected before any request).",
    {
        "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
        "path": {"type": "string", "description": "OCS path after /ocs/v2.php/, e.g. 'apps/spreed/api/v4/room'."},
        "params": {"type": "object", "default": {}, "description": "Query parameters (GET)."},
        "data": {"type": "object", "default": {}, "description": "Form fields (POST)."},
    },
    ["path"],
)
