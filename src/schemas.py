"""JSON-Schema definitions for all 52 nextcloud-tools.

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

# date-only, or date + time with optional seconds/fraction and optional Z/±HH:MM offset
ISO_DT = r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"

# --- files (WebDAV) ----------------------------------------------------------

NC_FILE_LIST = _s(
    "List entries of a folder: depth 0 = the entry itself, 1 (default) = direct children, recursive=true = the whole subtree.",
    {
        "path": {**PATH, "default": "/"},
        "depth": {"anyOf": [{"type": "integer", "enum": [0, 1]}, {"type": "string", "enum": ["0", "1", "infinity"]}], "default": 1, "description": "0 = the entry itself, 1 = direct children (default). Integer or legacy string form both accepted; 'infinity'/recursive=true = whole subtree."},
        "recursive": {"type": "boolean", "default": False, "description": "true = whole subtree (Depth: infinity) — cap with limit; equivalent to the legacy depth='infinity'."},
        "limit": {"type": "integer", "default": 200, "description": "Max entries returned."},
    },
)
NC_FILE_GET = _s(
    "Download a file. Text comes back as `content`, binary as `content_base64`; cap the size with max_bytes (default 100000, 0 = unlimited).",
    {
        "path": PATH,
        "raw": {"type": "boolean", "default": False, "description": "Force base64 even for text."},
        "max_bytes": {"type": "integer", "default": 100000, "description": "Max bytes returned; 0 = unlimited."},
    },
    ["path"],
)
NC_FILE_PUT = _s(
    "Create or overwrite a file. Use `content` for text or `content_base64` for binary; empty writes need allow_empty=true.",
    {
        "path": PATH,
        "content": {"type": "string", "default": "", "description": "Text content (utf-8)."},
        "content_base64": {"type": "string", "default": "", "description": "Base64-encoded binary content."},
        "content_type": {"type": "string", "default": "", "description": "Optional Content-Type header."},
        "allow_empty": {"type": "boolean", "default": False, "description": "Allow a 0-byte write; without it, empty content/content_base64 is rejected so an existing file is never clobbered to 0 bytes."},
    },
    ["path"],
)
NC_FILE_MKDIR = _s(
    "Create a folder.",
    {"path": PATH},
    ["path"],
)
NC_FILE_MOVE = _s(
    "Move or rename a file or folder to a new full path (`destination`).",
    {
        "source": {**PATH, "description": "Current path."},
        "destination": {**PATH, "description": "New full path."},
        "overwrite": {"type": "boolean", "default": True, "description": "Overwrite an existing destination (default true)."},
    },
    ["source", "destination"],
)

NC_FILE_COPY = _s(
    "Copy a file to a new full path (`destination`). Folders are not copied — use nc_file_move.",
    {
        "source": {**PATH, "description": "Current path."},
        "destination": {**PATH, "description": "New full path."},
        "overwrite": {"type": "boolean", "default": True, "description": "Overwrite an existing destination."},
    },
    ["source", "destination"],
)
NC_FILE_DELETE = _s(
    "Delete a file or folder (moves it to the trashbin).",
    {"path": PATH},
    ["path"],
)

# --- search ------------------------------------------------------------------

NC_SEARCH = _s(
    "Search across apps (files, file contents, Talk, calendar, tasks, contacts, notes) with one term.",
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
    "Search filenames inside a folder subtree (case-insensitive).",
    {
        "term": {"type": "string", "description": "Filename substring to match (case-insensitive)."},
        "path": {**PATH, "default": "/"},
        "limit": {"type": "integer", "default": 100, "description": "Max entries returned."},
    },
    ["term"],
)

# --- shares ------------------------------------------------------------------

NC_SHARE_LIST = _s(
    "List shares, optionally filtered to one path.",
    {"path": {**PATH, "default": ""}},
)
NC_SHARE_CREATE = _s(
    "Share a file or folder with a user/group (share_type 0) or as a public link (share_type 3).",
    {
        "path": PATH,
        "share_with": {"type": "string", "description": "User or group name (shareType 0)."},
        "share_type": {"type": "integer", "default": 0, "description": "0 = user/group, 3 = public link."},
        "permissions": {"type": "integer", "default": 1, "description": "Permission bitmask; 1 = read-only (default), 31 = all — pass explicitly."},
        "note": {"type": "string", "default": "", "description": "Optional note attached to the share."},
    },
    ["path", "share_with"],
)
NC_SHARE_DELETE = _s(
    "Delete a share by id.",
    {"id": {"type": "integer", "description": "Share id (from nc_share_list)."}},
    ["id"],
)

NC_SHARE_EDIT = _s(
    "Change an existing share: permissions, and for public links also password, expiry or note.",
    {
        "id": {"type": "integer", "description": "Share id (from nc_share_list)."},
        "permissions": {"type": "integer", "description": "Permission bitmask; 1 = read-only, 31 = all."},
        "password": {"type": "string", "description": "Link password (public links); '' clears."},
        "expire_date": {"type": "string", "description": "Expiry YYYY-MM-DD (public links); '' clears."},
        "note": {"type": "string", "description": "Share note; '' clears."},
    },
    ["id"],
)

# --- talk --------------------------------------------------------------------

NC_TALK_ROOMS = _s(
    "List Talk rooms (1:1 DMs only when talk_include_dms is enabled).",
    {"limit": {"type": "integer", "default": 50, "description": "Max rooms returned."}},
)
NC_TALK_MESSAGES = _s(
    "Read recent messages of a Talk room; paginate with last_known_message_id.",
    {
        "token": {"type": "string", "description": "Room token."},
        "limit": {"type": "integer", "default": 50, "description": "Max messages returned."},
        "last_known_message_id": {"type": "integer", "default": 0, "description": "Only messages after this id."},
    },
    ["token"],
)
NC_TALK_SEND = _s(
    "Send a message to a Talk room, optionally as a reply.",
    {
        "token": {"type": "string", "description": "Room token (from nc_talk_rooms)."},
        "message": {"type": "string", "description": "Message text to send."},
        "reply_to": {"type": "integer", "default": 0, "description": "Message id to reply to; 0 = top-level."},
    },
    ["token", "message"],
)
NC_TALK_DELETE = _s(
    "Delete a message from a Talk room.",
    {"token": {"type": "string", "description": "Room token."}, "message_id": {"type": "integer", "description": "Message id to delete."}},
    ["token", "message_id"],
)
NC_TALK_REACT = _s(
    "Add or remove an emoji reaction on a Talk message.",
    {
        "token": {"type": "string", "description": "Room token."},
        "message_id": {"type": "integer", "description": "Message id to react on."},
        "emoji": {"type": "string", "description": "Emoji, e.g. '👍'."},
        "react": {"type": "boolean", "default": True, "description": "true = add the reaction, false = remove it."},
    },
    ["token", "message_id", "emoji"],
)

# --- calendar + tasks ----------------------------------------------------------

NC_CAL_LIST = _s(
    "List calendar events in a time range (default: last 30 days to +90 days); recurring events are expanded.",
    {
        "calendar": {**CAL, "default": "personal"},
        "from": {"type": "string", "default": "", "pattern": ISO_DT,
                 "examples": ["2026-11-01T00:00:00+00:00", "2026-11-01"],
                 "description": "ISO 8601 range start (date-only or datetime; Z or ±HH:MM offset optional). Used exactly as given — no timezone conversion."},
        "to": {"type": "string", "default": "", "pattern": ISO_DT,
               "examples": ["2026-11-30T23:59:59Z", "2026-11-30"],
               "description": "ISO 8601 range end (date-only or datetime; Z or ±HH:MM offset optional). Used exactly as given — no timezone conversion."},
        "limit": {"type": "integer", "default": 100, "description": "Max events returned."},
    },
)

NC_CAL_LIST_CALENDARS = _s(
    "List the user's calendars; use a directory `name` as the `calendar` argument of nc_cal_*/nc_task_*.",
    {},
)
NC_CAL_CREATE = _s(
    "Create a calendar event: title, start/end, optional description, location, recurrence (rrule), reminder.",
    {
        "calendar": {**CAL, "default": "personal"},
        "summary": {"type": "string", "description": "Event title."},
        "start": {"type": "string", "pattern": ISO_DT,
                  "examples": ["2026-11-10T14:00:00+02:00", "2026-11-10T14:00:00Z", "2026-11-10"],
                  "description": "ISO 8601 start; a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as end. Used exactly as given — no timezone conversion."},
        "end": {"type": "string", "pattern": ISO_DT,
                "examples": ["2026-11-10T15:00:00+02:00", "2026-11-10T15:00:00Z", "2026-11-11"],
                "description": "ISO 8601 end; a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as start. Used exactly as given — no timezone conversion."},
        "all_day": {"type": "boolean", "default": False, "description": "true = all-day event (start/end as plain YYYY-MM-DD)."},
        "description": {"type": "string", "default": "", "description": "Event description."},
        "location": {"type": "string", "default": "", "description": "Event location."},
        "rrule": {"type": "string", "default": "", "description": "e.g. FREQ=DAILY;INTERVAL=2;COUNT=5 or FREQ=WEEKLY;BYDAY=MO,FR;UNTIL=20261231"},
        "reminder": {"type": "string", "default": "", "description": "Optional ISO 8601 duration for a reminder VALARM TRIGGER relative to start, e.g. '-PT15M' = 15 min before. Empty = no reminder."},
    },
    ["summary", "start", "end"],
)
NC_CAL_EDIT = _s(
    "Edit an existing event by UID; only the fields you pass are changed.",
    {
        "calendar": CAL,
        "uid": {"type": "string", "description": "VEVENT UID."},
        "summary": {"type": "string", "default": "", "description": "New title (empty = unchanged)."},
        "start": {"type": "string", "default": "", "pattern": ISO_DT,
                  "examples": ["2026-11-10T14:00:00+02:00", "2026-11-10"],
                  "description": "ISO 8601 start (empty = unchanged); a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as end. Used exactly as given — no timezone conversion."},
        "end": {"type": "string", "default": "", "pattern": ISO_DT,
                "examples": ["2026-11-10T15:00:00Z", "2026-11-11"],
                "description": "ISO 8601 end (empty = unchanged); a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as start. Used exactly as given — no timezone conversion."},
        "all_day": {"type": "boolean", "default": False, "description": "true = all-day event (start/end as plain YYYY-MM-DD)."},
        "description": {"type": "string", "default": "", "description": "New description (empty = unchanged)."},
        "location": {"type": "string", "default": "", "description": "New location (empty = unchanged)."},
        "rrule": {"type": "string", "default": "", "description": "New recurrence rule; '' removes it; omit to keep."},
        "reminder": {"type": ["string", "integer", "null"], "default": "", "description": "ISO 8601 duration string to set/replace the reminder VALARM (e.g. '-PT15M'); pass 0, null or '' to remove it."},
    },
    ["calendar", "uid"],
)
NC_CAL_DELETE = _s(
    "Delete a calendar event by UID.",
    {"calendar": CAL, "uid": {"type": "string", "description": "VEVENT UID as returned by nc_cal_list."}},
    ["calendar", "uid"],
)
NC_TASK_LIST = _s(
    "List tasks of a calendar (default 'tasks'), including completed ones.",
    {
        "calendar": {**CAL, "default": "tasks"},
        "include_completed": {"type": "boolean", "default": True, "description": "Include COMPLETED tasks (default true)."},
        "limit": {"type": "integer", "default": 200, "description": "Max tasks returned."},
    },
)
NC_TASK_CREATE = _s(
    "Create a task with a title and optional due date, priority, description and status.",
    {
        "calendar": {**CAL, "default": "tasks"},
        "summary": {"type": "string", "description": "Task title."},
        "due": {"type": "string", "default": "", "pattern": ISO_DT,
                "examples": ["2026-11-20T18:00:00+02:00", "2026-11-20"],
                "description": "ISO 8601 datetime, or YYYY-MM-DD (stored as all-day VALUE=DATE); empty = no due date. Used exactly as given — no timezone conversion."},
        "priority": {"type": "integer", "default": 0, "description": "1 = highest ... 9 = lowest; 0 = none."},
        "description": {"type": "string", "default": "", "description": "Task description."},
        "status": {"type": "string", "enum": ["NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"], "default": "NEEDS-ACTION", "description": "Initial STATUS of the new task; default NEEDS-ACTION (open). COMPLETED also sets COMPLETED timestamp and PERCENT-COMPLETE:100."},
    },
    ["summary"],
)
NC_TASK_COMPLETE = _s(
    "Mark a task as completed.",
    {"calendar": {**CAL, "default": "tasks"}, "uid": {"type": "string", "description": "VTODO UID as returned by nc_task_list."}},
    ["uid"],
)
NC_TASK_REOPEN = _s(
    "Reopen a completed task.",
    {"calendar": {**CAL, "default": "tasks"}, "uid": {"type": "string", "description": "VTODO UID as returned by nc_task_list."}},
    ["uid"],
)

# --- contacts ------------------------------------------------------------------

NC_CONTACT_LIST = _s(
    "List contacts of an address book (default 'contacts').",
    {"book": {**BOOK, "default": "contacts"}, "limit": {"type": "integer", "default": 500, "description": "Max contacts returned."}},
)

NC_CONTACT_LIST_BOOKS = _s(
    "List the user's address books; use a directory `name` as the `book` argument of nc_contact_*.",
    {},
)
NC_CONTACT_SEARCH = _s(
    "Search contacts by name, email or phone (case-insensitive).",
    {"book": {**BOOK, "default": "contacts"}, "term": {"type": "string", "description": "Substring matched against name/email/phone (case-insensitive)."}},
    ["term"],
)
NC_CONTACT_GET = _s(
    "Get one contact by UID.",
    {"book": {**BOOK, "default": "contacts"}, "uid": {"type": "string", "description": "Contact UID (from nc_contact_list)."}},
    ["uid"],
)
NC_CONTACT_CREATE = _s(
    "Create a contact with a full name and optional email, phone, org and note.",
    {
        "book": {**BOOK, "default": "contacts"},
        "fn": {"type": "string", "description": "Full name (required by vCard)."},
        "email": {"type": "string", "default": "", "description": "Email address."},
        "phone": {"type": "string", "default": "", "description": "Phone number."},
        "org": {"type": "string", "default": "", "description": "Organization."},
        "note": {"type": "string", "default": "", "description": "Free-form note."},
    },
    ["fn"],
)
NC_CONTACT_EDIT = _s(
    "Edit a contact by UID; only the fields you pass are changed.",
    {
        "book": {**BOOK, "default": "contacts"},
        "uid": {"type": "string", "description": "Contact UID to edit (from nc_contact_list)."},
        "fn": {"type": "string", "default": "", "description": "New full name (empty = unchanged)."},
        "email": {"type": ["string", "array"], "items": {"type": "string"}, "default": "", "description": "Email address or list of addresses; pass '' or [] to clear all. Omit to keep existing."},
        "phone": {"type": ["string", "array"], "items": {"type": "string"}, "default": "", "description": "Phone number or list of numbers; pass '' or [] to clear all. Omit to keep existing."},
        "org": {"type": "string", "default": "", "description": "New organization; '' clears it; omit to keep."},
        "note": {"type": "string", "default": "", "description": "New note; '' clears it; omit to keep."},
    },
    ["uid"],
)

# --- notes ---------------------------------------------------------------------

NC_NOTE_LIST = _s(
    "List notes, optionally filtered by category.",
    {
        "category": {"type": "string", "default": "", "description": "Restrict to this category (empty = all)."},
        "limit": {"type": "integer", "default": 50, "description": "Max notes returned."},
        "with_content": {"type": "boolean", "default": False, "description": "DAV fallback: include a 200-char content preview per note (costs one GET per note)."},
    },
)
NC_NOTE_GET = _s(
    "Get one full note by id (or title).",
    {"id": {"type": "string", "description": "Note id (API) or title (DAV fallback)."}},
    ["id"],
)
NC_NOTE_CREATE = _s(
    "Create a note with a title and optional markdown content and category.",
    {
        "title": {"type": "string", "description": "Note title (also the DAV filename)."},
        "content": {"type": "string", "default": "", "description": "Note body (markdown)."},
        "category": {"type": "string", "default": "", "description": "Category (folder)."},
    },
    ["title"],
)
NC_NOTE_EDIT = _s(
    "Edit a note's content and/or title.",
    {"id": {"type": "string", "description": "Note id (API) or title (DAV fallback)."}, "content": {"type": "string", "default": "", "description": "New content; '' clears the note."}, "title": {"type": "string", "default": "", "description": "New title (renames the note)."}},
    ["id"],
)
NC_NOTE_DELETE = _s(
    "Delete a note.",
    {"id": {"type": "string", "description": "Note id (API) or title (DAV fallback)."}},
    ["id"],
)

# --- misc ----------------------------------------------------------------------

NC_ACTIVITY = _s(
    "Recent activity of the bot account.",
    {
        "limit": {"type": "integer", "default": 50, "description": "Max entries returned."},
        "since": {"type": "integer", "default": 0, "description": "Unix timestamp; only newer entries."},
    },
)
NC_NOTIFICATIONS = _s(
    "Pending notifications of the bot account.",
    {"limit": {"type": "integer", "default": 50, "description": "Max notifications returned."}},
)
NC_TAG_LIST = _s("List all system tags.", {})
NC_TAG_ASSIGN = _s(
    "Assign a system tag to a file or folder.",
    {"path": PATH, "tag": {"type": "string", "description": "Tag name (see nc_tag_list)."}},
    ["path", "tag"],
)
NC_TAG_UNASSIGN = _s(
    "Remove a system tag from a file or folder.",
    {"path": PATH, "tag": {"type": "string", "description": "Tag name (see nc_tag_list)."}},
    ["path", "tag"],
)
NC_TRASH_LIST = _s(
    "List trashbin entries (original location, deletion time, size).",
    {"limit": {"type": "integer", "default": 100, "description": "Max entries returned."}},
)
NC_TRASH_RESTORE = _s(
    "Restore a trashbin entry to its original location.",
    {"trash_path": {"type": "string", "description": "Trash path as returned by nc_trash_list."}},
    ["trash_path"],
)
NC_TRASH_EMPTY = _s(
    "Empty the entire trashbin.",
    {},
)
NC_COMMENT_LIST = _s(
    "List comments on a file (give `file_id` or `path`).",
    {
        "file_id": {"type": "string", "default": "", "description": "Numeric file id; skips the path->oc:fileid PROPFIND."},
        "path": {**PATH, "default": ""},
    },
)
NC_COMMENT_ADD = _s(
    "Add a comment to a file (give `file_id` or `path`).",
    {
        "file_id": {"type": "string", "default": "", "description": "Numeric file id; skips the path->oc:fileid PROPFIND."},
        "path": {**PATH, "default": ""},
        "message": {"type": "string", "description": "Comment text (required, non-empty)."},
    },
    ["message"],
)
NC_COMMENT_DELETE = _s(
    "Delete a comment from a file (give `file_id` or `path`).",
    {
        "file_id": {"type": "string", "default": "", "description": "Numeric file id; skips the path->oc:fileid PROPFIND."},
        "path": {**PATH, "default": ""},
        "comment_id": {"type": "integer", "description": "Comment id, as returned by nc_comment_list."},
    },
    ["comment_id"],
)
NC_OCS = _s(
    "Call any unmapped OCS v2 endpoint under /ocs/v2.php/ directly (method, path, query params, form data).",
    {
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET", "description": "HTTP method; GET is read-only, DELETE is destructive, POST/PUT/PATCH are gated writes."},
        "path": {"type": "string", "description": "OCS path after /ocs/v2.php/, e.g. 'apps/spreed/api/v4/room'."},
        "params": {"type": "object", "default": {}, "description": "Query parameters (GET/DELETE)."},
        "data": {"type": "object", "default": {}, "description": "Form fields (POST/PUT/PATCH)."},
    },
    ["path"],
)
NC_FILE_UNLOCK = _s(
    "Force-unlock a file locked by the files_lock app (e.g. a stale lock).",
    {
        "path": PATH,
        "file_id": {"type": "string", "default": "", "description": "Numeric file id; resolved from `path` when omitted."},
    },
    ["path"],
)

NC_VERSION = _s(
    "Nextcloud server version via GET /status.php: returns only 'version' (e.g. '35.0.2.2') and 'versionstring' (e.g. '35.0.2').",
    {},
)
