/* nextcloud-tools dashboard tab: lists all nc_* tools with per-tool enable/disable and approval-gate toggle.
 * Plain IIFE bundle — no build step, no imports. React and UI components come
 * from window.__HERMES_PLUGIN_SDK__; registration name must match manifest.json.
 * Layout/styling lives in dist/style.css (.nc-* classes) and uses only theme
 * CSS vars, so colors always follow the user-selected dashboard theme.
 * Parameter docs: plugin API routes are mounted at host startup and cached per
 * process, so a host started before plugin v0.24.0 still serves GET /tools
 * without `parameters`. The generated TOOL_DOCS block below (rewritten by
 * `python3 dashboard/build_docs.py`, pinned by tests/test_dashboard_docs.py) is
 * the fallback; the live API payload wins when it carries `parameters`.
 */
(function () {
  "use strict";
  if (!window.__HERMES_PLUGINS__ || !window.__HERMES_PLUGIN_SDK__) return;

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useMemo = SDK.hooks.useMemo;
  var useToast = SDK.hooks.useToast;
  var cn = SDK.utils.cn;
  var Card = SDK.components.Card;
  var CardHeader = SDK.components.CardHeader;
  var CardTitle = SDK.components.CardTitle;
  var CardContent = SDK.components.CardContent;
  var Badge = SDK.components.Badge;
  var Button = SDK.components.Button; // fallback toggle on hosts without Checkbox
  var Checkbox = SDK.components.Checkbox;
  var Toast = SDK.components.Toast;
  var Tabs = SDK.components.Tabs;
  var TabsList = SDK.components.TabsList;
  var TabsTrigger = SDK.components.TabsTrigger;
  var Select = SDK.components.Select;
  var SelectOption = SDK.components.SelectOption;
  var Separator = SDK.components.Separator;
  var Input = SDK.components.Input;

  var API = "/api/plugins/nextcloud-tools";

  // BEGIN GENERATED TOOL DOCS (dashboard/build_docs.py)
var TOOL_DOCS = {
 "nc_activity": {
  "description": "Recent activity of the bot account.",
  "parameters": {
   "properties": {
    "limit": {
     "default": 50,
     "description": "Max entries returned.",
     "type": "integer"
    },
    "since": {
     "default": 0,
     "description": "Unix timestamp; only newer entries.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_cal_create": {
  "description": "Create a calendar event: title, start/end, optional description, location, recurrence (rrule), reminder.",
  "parameters": {
   "properties": {
    "all_day": {
     "default": false,
     "description": "true = all-day event (start/end as plain YYYY-MM-DD).",
     "type": "boolean"
    },
    "calendar": {
     "default": "personal",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "description": {
     "default": "",
     "description": "Event description.",
     "type": "string"
    },
    "end": {
     "description": "ISO 8601 end; a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as start. Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-10T15:00:00+02:00",
      "2026-11-10T15:00:00Z",
      "2026-11-11"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "location": {
     "default": "",
     "description": "Event location.",
     "type": "string"
    },
    "reminder": {
     "default": "",
     "description": "Optional ISO 8601 duration for a reminder VALARM TRIGGER relative to start, e.g. '-PT15M' = 15 min before. Empty = no reminder.",
     "type": "string"
    },
    "rrule": {
     "default": "",
     "description": "e.g. FREQ=DAILY;INTERVAL=2;COUNT=5 or FREQ=WEEKLY;BYDAY=MO,FR;UNTIL=20261231",
     "type": "string"
    },
    "start": {
     "description": "ISO 8601 start; a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as end. Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-10T14:00:00+02:00",
      "2026-11-10T14:00:00Z",
      "2026-11-10"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "summary": {
     "description": "Event title.",
     "type": "string"
    }
   },
   "required": [
    "summary",
    "start",
    "end"
   ],
   "type": "object"
  }
 },
 "nc_cal_delete": {
  "description": "Delete a calendar event by UID.",
  "parameters": {
   "properties": {
    "calendar": {
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "uid": {
     "description": "VEVENT UID as returned by nc_cal_list.",
     "type": "string"
    }
   },
   "required": [
    "calendar",
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_cal_edit": {
  "description": "Edit an existing event by UID; only the fields you pass are changed.",
  "parameters": {
   "properties": {
    "all_day": {
     "default": false,
     "description": "true = all-day event (start/end as plain YYYY-MM-DD).",
     "type": "boolean"
    },
    "calendar": {
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "description": {
     "default": "",
     "description": "New description (empty = unchanged).",
     "type": "string"
    },
    "end": {
     "default": "",
     "description": "ISO 8601 end (empty = unchanged); a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as start. Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-10T15:00:00Z",
      "2026-11-11"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "location": {
     "default": "",
     "description": "New location (empty = unchanged).",
     "type": "string"
    },
    "reminder": {
     "default": "",
     "description": "ISO 8601 duration string to set/replace the reminder VALARM (e.g. '-PT15M'); pass 0, null or '' to remove it.",
     "type": [
      "string",
      "integer",
      "null"
     ]
    },
    "rrule": {
     "default": "",
     "description": "New recurrence rule; '' removes it; omit to keep.",
     "type": "string"
    },
    "start": {
     "default": "",
     "description": "ISO 8601 start (empty = unchanged); a plain YYYY-MM-DD only together with all_day=true. Use the same offset style as end. Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-10T14:00:00+02:00",
      "2026-11-10"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "summary": {
     "default": "",
     "description": "New title (empty = unchanged).",
     "type": "string"
    },
    "uid": {
     "description": "VEVENT UID.",
     "type": "string"
    }
   },
   "required": [
    "calendar",
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_cal_list": {
  "description": "List calendar events in a time range (default: last 30 days to +90 days); recurring events are expanded.",
  "parameters": {
   "properties": {
    "calendar": {
     "default": "personal",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "from": {
     "default": "",
     "description": "ISO 8601 range start (date-only or datetime; Z or ±HH:MM offset optional). Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-01T00:00:00+00:00",
      "2026-11-01"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "limit": {
     "default": 100,
     "description": "Max events returned.",
     "type": "integer"
    },
    "to": {
     "default": "",
     "description": "ISO 8601 range end (date-only or datetime; Z or ±HH:MM offset optional). Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-30T23:59:59Z",
      "2026-11-30"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_cal_list_calendars": {
  "description": "List the user's calendars; use a directory `name` as the `calendar` argument of nc_cal_*/nc_task_*.",
  "parameters": {
   "properties": {},
   "required": [],
   "type": "object"
  }
 },
 "nc_comment_add": {
  "description": "Add a comment to a file (give `file_id` or `path`).",
  "parameters": {
   "properties": {
    "file_id": {
     "default": "",
     "description": "Numeric file id; skips the path->oc:fileid PROPFIND.",
     "type": "string"
    },
    "message": {
     "description": "Comment text (required, non-empty).",
     "type": "string"
    },
    "path": {
     "default": "",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "message"
   ],
   "type": "object"
  }
 },
 "nc_comment_delete": {
  "description": "Delete a comment from a file (give `file_id` or `path`).",
  "parameters": {
   "properties": {
    "comment_id": {
     "description": "Comment id, as returned by nc_comment_list.",
     "type": "integer"
    },
    "file_id": {
     "default": "",
     "description": "Numeric file id; skips the path->oc:fileid PROPFIND.",
     "type": "string"
    },
    "path": {
     "default": "",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "comment_id"
   ],
   "type": "object"
  }
 },
 "nc_comment_list": {
  "description": "List comments on a file (give `file_id` or `path`).",
  "parameters": {
   "properties": {
    "file_id": {
     "default": "",
     "description": "Numeric file id; skips the path->oc:fileid PROPFIND.",
     "type": "string"
    },
    "path": {
     "default": "",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_contact_create": {
  "description": "Create a contact with a full name and optional email, phone, org and note.",
  "parameters": {
   "properties": {
    "book": {
     "default": "contacts",
     "description": "Address book DAV directory name.",
     "type": "string"
    },
    "email": {
     "default": "",
     "description": "Email address.",
     "type": "string"
    },
    "fn": {
     "description": "Full name (required by vCard).",
     "type": "string"
    },
    "note": {
     "default": "",
     "description": "Free-form note.",
     "type": "string"
    },
    "org": {
     "default": "",
     "description": "Organization.",
     "type": "string"
    },
    "phone": {
     "default": "",
     "description": "Phone number.",
     "type": "string"
    }
   },
   "required": [
    "fn"
   ],
   "type": "object"
  }
 },
 "nc_contact_edit": {
  "description": "Edit a contact by UID; only the fields you pass are changed.",
  "parameters": {
   "properties": {
    "book": {
     "default": "contacts",
     "description": "Address book DAV directory name.",
     "type": "string"
    },
    "email": {
     "default": "",
     "description": "Email address or list of addresses; pass '' or [] to clear all. Omit to keep existing.",
     "items": {
      "type": "string"
     },
     "type": [
      "string",
      "array"
     ]
    },
    "fn": {
     "default": "",
     "description": "New full name (empty = unchanged).",
     "type": "string"
    },
    "note": {
     "default": "",
     "description": "New note; '' clears it; omit to keep.",
     "type": "string"
    },
    "org": {
     "default": "",
     "description": "New organization; '' clears it; omit to keep.",
     "type": "string"
    },
    "phone": {
     "default": "",
     "description": "Phone number or list of numbers; pass '' or [] to clear all. Omit to keep existing.",
     "items": {
      "type": "string"
     },
     "type": [
      "string",
      "array"
     ]
    },
    "uid": {
     "description": "Contact UID to edit (from nc_contact_list).",
     "type": "string"
    }
   },
   "required": [
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_contact_get": {
  "description": "Get one contact by UID.",
  "parameters": {
   "properties": {
    "book": {
     "default": "contacts",
     "description": "Address book DAV directory name.",
     "type": "string"
    },
    "uid": {
     "description": "Contact UID (from nc_contact_list).",
     "type": "string"
    }
   },
   "required": [
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_contact_list": {
  "description": "List contacts of an address book (default 'contacts').",
  "parameters": {
   "properties": {
    "book": {
     "default": "contacts",
     "description": "Address book DAV directory name.",
     "type": "string"
    },
    "limit": {
     "default": 500,
     "description": "Max contacts returned.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_contact_list_books": {
  "description": "List the user's address books; use a directory `name` as the `book` argument of nc_contact_*.",
  "parameters": {
   "properties": {},
   "required": [],
   "type": "object"
  }
 },
 "nc_contact_search": {
  "description": "Search contacts by name, email or phone (case-insensitive).",
  "parameters": {
   "properties": {
    "book": {
     "default": "contacts",
     "description": "Address book DAV directory name.",
     "type": "string"
    },
    "term": {
     "description": "Substring matched against name/email/phone (case-insensitive).",
     "type": "string"
    }
   },
   "required": [
    "term"
   ],
   "type": "object"
  }
 },
 "nc_file_copy": {
  "description": "Copy a file to a new full path (`destination`). Folders are not copied — use nc_file_move.",
  "parameters": {
   "properties": {
    "destination": {
     "description": "New full path.",
     "type": "string"
    },
    "overwrite": {
     "default": true,
     "description": "Overwrite an existing destination.",
     "type": "boolean"
    },
    "source": {
     "description": "Current path.",
     "type": "string"
    }
   },
   "required": [
    "source",
    "destination"
   ],
   "type": "object"
  }
 },
 "nc_file_delete": {
  "description": "Delete a file or folder (moves it to the trashbin).",
  "parameters": {
   "properties": {
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_file_get": {
  "description": "Download a file. Text comes back as `content`, binary as `content_base64`; cap the size with max_bytes (default 100000, 0 = unlimited).",
  "parameters": {
   "properties": {
    "max_bytes": {
     "default": 100000,
     "description": "Max bytes returned; 0 = unlimited.",
     "type": "integer"
    },
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "raw": {
     "default": false,
     "description": "Force base64 even for text.",
     "type": "boolean"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_file_list": {
  "description": "List entries of a folder: depth 0 = the entry itself, 1 (default) = direct children, recursive=true = the whole subtree.",
  "parameters": {
   "properties": {
    "depth": {
     "anyOf": [
      {
       "enum": [
        0,
        1
       ],
       "type": "integer"
      },
      {
       "enum": [
        "0",
        "1",
        "infinity"
       ],
       "type": "string"
      }
     ],
     "default": 1,
     "description": "0 = the entry itself, 1 = direct children (default). Integer or legacy string form both accepted; 'infinity'/recursive=true = whole subtree."
    },
    "limit": {
     "default": 200,
     "description": "Max entries returned.",
     "type": "integer"
    },
    "path": {
     "default": "/",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "recursive": {
     "default": false,
     "description": "true = whole subtree (Depth: infinity) — cap with limit; equivalent to the legacy depth='infinity'.",
     "type": "boolean"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_file_mkdir": {
  "description": "Create a folder.",
  "parameters": {
   "properties": {
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_file_move": {
  "description": "Move or rename a file or folder to a new full path (`destination`).",
  "parameters": {
   "properties": {
    "destination": {
     "description": "New full path.",
     "type": "string"
    },
    "overwrite": {
     "default": true,
     "description": "Overwrite an existing destination (default true).",
     "type": "boolean"
    },
    "source": {
     "description": "Current path.",
     "type": "string"
    }
   },
   "required": [
    "source",
    "destination"
   ],
   "type": "object"
  }
 },
 "nc_file_put": {
  "description": "Create or overwrite a file. Use `content` for text or `content_base64` for binary; empty writes need allow_empty=true.",
  "parameters": {
   "properties": {
    "allow_empty": {
     "default": false,
     "description": "Allow a 0-byte write; without it, empty content/content_base64 is rejected so an existing file is never clobbered to 0 bytes.",
     "type": "boolean"
    },
    "content": {
     "default": "",
     "description": "Text content (utf-8).",
     "type": "string"
    },
    "content_base64": {
     "default": "",
     "description": "Base64-encoded binary content.",
     "type": "string"
    },
    "content_type": {
     "default": "",
     "description": "Optional Content-Type header.",
     "type": "string"
    },
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_file_search": {
  "description": "Search filenames inside a folder subtree (case-insensitive).",
  "parameters": {
   "properties": {
    "limit": {
     "default": 100,
     "description": "Max entries returned.",
     "type": "integer"
    },
    "path": {
     "default": "/",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "term": {
     "description": "Filename substring to match (case-insensitive).",
     "type": "string"
    }
   },
   "required": [
    "term"
   ],
   "type": "object"
  }
 },
 "nc_file_unlock": {
  "description": "Force-unlock a file locked by the files_lock app (e.g. a stale lock).",
  "parameters": {
   "properties": {
    "file_id": {
     "default": "",
     "description": "Numeric file id; resolved from `path` when omitted.",
     "type": "string"
    },
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_note_create": {
  "description": "Create a note with a title and optional markdown content and category.",
  "parameters": {
   "properties": {
    "category": {
     "default": "",
     "description": "Category (folder).",
     "type": "string"
    },
    "content": {
     "default": "",
     "description": "Note body (markdown).",
     "type": "string"
    },
    "title": {
     "description": "Note title (also the DAV filename).",
     "type": "string"
    }
   },
   "required": [
    "title"
   ],
   "type": "object"
  }
 },
 "nc_note_delete": {
  "description": "Delete a note.",
  "parameters": {
   "properties": {
    "id": {
     "description": "Note id (API) or title (DAV fallback).",
     "type": "string"
    }
   },
   "required": [
    "id"
   ],
   "type": "object"
  }
 },
 "nc_note_edit": {
  "description": "Edit a note's content and/or title.",
  "parameters": {
   "properties": {
    "content": {
     "default": "",
     "description": "New content; '' clears the note.",
     "type": "string"
    },
    "id": {
     "description": "Note id (API) or title (DAV fallback).",
     "type": "string"
    },
    "title": {
     "default": "",
     "description": "New title (renames the note).",
     "type": "string"
    }
   },
   "required": [
    "id"
   ],
   "type": "object"
  }
 },
 "nc_note_get": {
  "description": "Get one full note by id (or title).",
  "parameters": {
   "properties": {
    "id": {
     "description": "Note id (API) or title (DAV fallback).",
     "type": "string"
    }
   },
   "required": [
    "id"
   ],
   "type": "object"
  }
 },
 "nc_note_list": {
  "description": "List notes, optionally filtered by category.",
  "parameters": {
   "properties": {
    "category": {
     "default": "",
     "description": "Restrict to this category (empty = all).",
     "type": "string"
    },
    "limit": {
     "default": 50,
     "description": "Max notes returned.",
     "type": "integer"
    },
    "with_content": {
     "default": false,
     "description": "DAV fallback: include a 200-char content preview per note (costs one GET per note).",
     "type": "boolean"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_notifications": {
  "description": "Pending notifications of the bot account.",
  "parameters": {
   "properties": {
    "limit": {
     "default": 50,
     "description": "Max notifications returned.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_ocs": {
  "description": "Call any unmapped OCS v2 endpoint under /ocs/v2.php/ directly (method, path, query params, form data).",
  "parameters": {
   "properties": {
    "data": {
     "default": {},
     "description": "Form fields (POST/PUT/PATCH).",
     "type": "object"
    },
    "method": {
     "default": "GET",
     "description": "HTTP method; GET is read-only, DELETE is destructive, POST/PUT/PATCH are gated writes.",
     "enum": [
      "GET",
      "POST",
      "PUT",
      "DELETE",
      "PATCH"
     ],
     "type": "string"
    },
    "params": {
     "default": {},
     "description": "Query parameters (GET/DELETE).",
     "type": "object"
    },
    "path": {
     "description": "OCS path after /ocs/v2.php/, e.g. 'apps/spreed/api/v4/room'.",
     "type": "string"
    }
   },
   "required": [
    "path"
   ],
   "type": "object"
  }
 },
 "nc_search": {
  "description": "Search across apps (files, file contents, Talk, calendar, tasks, contacts, notes) with one term.",
  "parameters": {
   "properties": {
    "limit": {
     "default": 0,
     "description": "Per-provider limit; 0 = settings max_results.",
     "type": "integer"
    },
    "providers": {
     "default": [],
     "description": "Provider ids; empty = settings default_search_providers.",
     "items": {
      "type": "string"
     },
     "type": "array"
    },
    "term": {
     "description": "Search term.",
     "type": "string"
    }
   },
   "required": [
    "term"
   ],
   "type": "object"
  }
 },
 "nc_share_create": {
  "description": "Share a file or folder with a user/group (share_type 0) or as a public link (share_type 3).",
  "parameters": {
   "properties": {
    "note": {
     "default": "",
     "description": "Optional note attached to the share.",
     "type": "string"
    },
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "permissions": {
     "default": 1,
     "description": "Permission bitmask; 1 = read-only (default), 31 = all — pass explicitly.",
     "type": "integer"
    },
    "share_type": {
     "default": 0,
     "description": "0 = user/group, 3 = public link.",
     "type": "integer"
    },
    "share_with": {
     "description": "User or group name (shareType 0).",
     "type": "string"
    }
   },
   "required": [
    "path",
    "share_with"
   ],
   "type": "object"
  }
 },
 "nc_share_delete": {
  "description": "Delete a share by id.",
  "parameters": {
   "properties": {
    "id": {
     "description": "Share id (from nc_share_list).",
     "type": "integer"
    }
   },
   "required": [
    "id"
   ],
   "type": "object"
  }
 },
 "nc_share_edit": {
  "description": "Change an existing share: permissions, and for public links also password, expiry or note.",
  "parameters": {
   "properties": {
    "expire_date": {
     "description": "Expiry YYYY-MM-DD (public links); '' clears.",
     "type": "string"
    },
    "id": {
     "description": "Share id (from nc_share_list).",
     "type": "integer"
    },
    "note": {
     "description": "Share note; '' clears.",
     "type": "string"
    },
    "password": {
     "description": "Link password (public links); '' clears.",
     "type": "string"
    },
    "permissions": {
     "description": "Permission bitmask; 1 = read-only, 31 = all.",
     "type": "integer"
    }
   },
   "required": [
    "id"
   ],
   "type": "object"
  }
 },
 "nc_share_list": {
  "description": "List shares, optionally filtered to one path.",
  "parameters": {
   "properties": {
    "path": {
     "default": "",
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_tag_assign": {
  "description": "Assign a system tag to a file or folder.",
  "parameters": {
   "properties": {
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "tag": {
     "description": "Tag name (see nc_tag_list).",
     "type": "string"
    }
   },
   "required": [
    "path",
    "tag"
   ],
   "type": "object"
  }
 },
 "nc_tag_list": {
  "description": "List all system tags.",
  "parameters": {
   "properties": {},
   "required": [],
   "type": "object"
  }
 },
 "nc_tag_unassign": {
  "description": "Remove a system tag from a file or folder.",
  "parameters": {
   "properties": {
    "path": {
     "description": "Server-side path, e.g. '/Documents/report.pdf'.",
     "type": "string"
    },
    "tag": {
     "description": "Tag name (see nc_tag_list).",
     "type": "string"
    }
   },
   "required": [
    "path",
    "tag"
   ],
   "type": "object"
  }
 },
 "nc_talk_delete": {
  "description": "Delete a message from a Talk room.",
  "parameters": {
   "properties": {
    "message_id": {
     "description": "Message id to delete.",
     "type": "integer"
    },
    "token": {
     "description": "Room token.",
     "type": "string"
    }
   },
   "required": [
    "token",
    "message_id"
   ],
   "type": "object"
  }
 },
 "nc_talk_messages": {
  "description": "Read recent messages of a Talk room; paginate with last_known_message_id.",
  "parameters": {
   "properties": {
    "last_known_message_id": {
     "default": 0,
     "description": "Only messages after this id.",
     "type": "integer"
    },
    "limit": {
     "default": 50,
     "description": "Max messages returned.",
     "type": "integer"
    },
    "token": {
     "description": "Room token.",
     "type": "string"
    }
   },
   "required": [
    "token"
   ],
   "type": "object"
  }
 },
 "nc_talk_react": {
  "description": "Add or remove an emoji reaction on a Talk message.",
  "parameters": {
   "properties": {
    "emoji": {
     "description": "Emoji, e.g. '👍'.",
     "type": "string"
    },
    "message_id": {
     "description": "Message id to react on.",
     "type": "integer"
    },
    "react": {
     "default": true,
     "description": "true = add the reaction, false = remove it.",
     "type": "boolean"
    },
    "token": {
     "description": "Room token.",
     "type": "string"
    }
   },
   "required": [
    "token",
    "message_id",
    "emoji"
   ],
   "type": "object"
  }
 },
 "nc_talk_rooms": {
  "description": "List Talk rooms (1:1 DMs only when talk_include_dms is enabled).",
  "parameters": {
   "properties": {
    "limit": {
     "default": 50,
     "description": "Max rooms returned.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_talk_send": {
  "description": "Send a message to a Talk room, optionally as a reply.",
  "parameters": {
   "properties": {
    "message": {
     "description": "Message text to send.",
     "type": "string"
    },
    "reply_to": {
     "default": 0,
     "description": "Message id to reply to; 0 = top-level.",
     "type": "integer"
    },
    "token": {
     "description": "Room token (from nc_talk_rooms).",
     "type": "string"
    }
   },
   "required": [
    "token",
    "message"
   ],
   "type": "object"
  }
 },
 "nc_task_complete": {
  "description": "Mark a task as completed.",
  "parameters": {
   "properties": {
    "calendar": {
     "default": "tasks",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "uid": {
     "description": "VTODO UID as returned by nc_task_list.",
     "type": "string"
    }
   },
   "required": [
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_task_create": {
  "description": "Create a task with a title and optional due date, priority, description and status.",
  "parameters": {
   "properties": {
    "calendar": {
     "default": "tasks",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "description": {
     "default": "",
     "description": "Task description.",
     "type": "string"
    },
    "due": {
     "default": "",
     "description": "ISO 8601 datetime, or YYYY-MM-DD (stored as all-day VALUE=DATE); empty = no due date. Used exactly as given — no timezone conversion.",
     "examples": [
      "2026-11-20T18:00:00+02:00",
      "2026-11-20"
     ],
     "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})?)?$",
     "type": "string"
    },
    "priority": {
     "default": 0,
     "description": "1 = highest ... 9 = lowest; 0 = none.",
     "type": "integer"
    },
    "status": {
     "default": "NEEDS-ACTION",
     "description": "Initial STATUS of the new task; default NEEDS-ACTION (open). COMPLETED also sets COMPLETED timestamp and PERCENT-COMPLETE:100.",
     "enum": [
      "NEEDS-ACTION",
      "IN-PROCESS",
      "COMPLETED",
      "CANCELLED"
     ],
     "type": "string"
    },
    "summary": {
     "description": "Task title.",
     "type": "string"
    }
   },
   "required": [
    "summary"
   ],
   "type": "object"
  }
 },
 "nc_task_list": {
  "description": "List tasks of a calendar (default 'tasks'), including completed ones.",
  "parameters": {
   "properties": {
    "calendar": {
     "default": "tasks",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "include_completed": {
     "default": true,
     "description": "Include COMPLETED tasks (default true).",
     "type": "boolean"
    },
    "limit": {
     "default": 200,
     "description": "Max tasks returned.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_task_reopen": {
  "description": "Reopen a completed task.",
  "parameters": {
   "properties": {
    "calendar": {
     "default": "tasks",
     "description": "Calendar DAV directory name (NOT the display name). Shared calendars: '<name>_shared_by_<Owner>'.",
     "type": "string"
    },
    "uid": {
     "description": "VTODO UID as returned by nc_task_list.",
     "type": "string"
    }
   },
   "required": [
    "uid"
   ],
   "type": "object"
  }
 },
 "nc_trash_empty": {
  "description": "Empty the entire trashbin.",
  "parameters": {
   "properties": {},
   "required": [],
   "type": "object"
  }
 },
 "nc_trash_list": {
  "description": "List trashbin entries (original location, deletion time, size).",
  "parameters": {
   "properties": {
    "limit": {
     "default": 100,
     "description": "Max entries returned.",
     "type": "integer"
    }
   },
   "required": [],
   "type": "object"
  }
 },
 "nc_trash_restore": {
  "description": "Restore a trashbin entry to its original location.",
  "parameters": {
   "properties": {
    "trash_path": {
     "description": "Trash path as returned by nc_trash_list.",
     "type": "string"
    }
   },
   "required": [
    "trash_path"
   ],
   "type": "object"
  }
 },
 "nc_version": {
  "description": "Nextcloud server version via GET /status.php: returns only 'version' (e.g. '35.0.2.2') and 'versionstring' (e.g. '35.0.2').",
  "parameters": {
   "properties": {},
   "required": [],
   "type": "object"
  }
 }
};
// END GENERATED TOOL DOCS

  /* Ordered [id, name-prefix, label]; first prefix match wins, else "other". */
  var CATEGORIES = [
    ["files", "nc_file_", "Files"],
    ["search", "nc_search", "Search"],
    ["shares", "nc_share_", "Shares"],
    ["talk", "nc_talk_", "Talk"],
    ["cal", "nc_cal_", "Calendar"],
    ["tasks", "nc_task_", "Tasks"],
    ["contacts", "nc_contact_", "Contacts"],
    ["notes", "nc_note_", "Notes"],
    ["activity", "nc_activity", "Activity"],
    ["notifications", "nc_notifications", "Notifications"],
    ["tags", "nc_tag_", "Tags"],
    ["trash", "nc_trash_", "Trashbin"],
    ["comments", "nc_comment", "Comments"],
    ["ocs", "nc_ocs", "OCS"]
  ];

  function categoryOf(name) {
    for (var i = 0; i < CATEGORIES.length; i++) {
      if (name.indexOf(CATEGORIES[i][1]) === 0) return CATEGORIES[i][0];
    }
    return "other";
  }

  /* Badge tone per gate class (Badge takes `tone`, not `variant`). */
  var GATE_TONE = {
    read: "secondary",
    write: "default",
    destructive: "destructive",
    mixed: "outline"
  };

  function NextcloudToolsPage() {
    var toolsState = useState([]);
    var tools = toolsState[0];
    var setTools = toolsState[1];
    var errState = useState(null);
    var error = errState[0];
    var setError = errState[1];
    var busyState = useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];
    var queryState = useState("");
    var query = queryState[0];
    var setQuery = queryState[1];
    var gateState = useState("all");
    var gateFilter = gateState[0];
    var setGateFilter = gateState[1];
    var expandedState = useState({}); // map tool name -> bool; several rows may be open at once
    var expanded = expandedState[0];
    var setExpanded = expandedState[1];
    var toastState = useToast ? useToast() : null; // older hosts: inline error paragraph

    function notify(msg, tone) {
      if (toastState && toastState.showToast) toastState.showToast(msg, tone);
      else setError(tone === "error" ? msg : null);
    }

    function fetchTools() {
      return SDK.fetchJSON(API + "/tools", { cache: "no-store" }).then(function (data) {
        return data.tools || [];
      });
    }

    useEffect(function () {
      var cancelled = false;
      fetchTools()
        .then(function (list) {
          if (!cancelled) setTools(list);
        })
        .catch(function (err) {
          if (!cancelled) notify(String((err && err.message) || err), "error");
        });
      return function () {
        cancelled = true;
      };
    }, []);

    function toggle(t) {
      if (busy) return; // one PUT at a time — concurrent writes race on the same config key
      setBusy(true);
      setError(null);
      SDK.fetchJSON(API + "/tools/" + encodeURIComponent(t.name), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !t.enabled })
      })
        .then(function () {
          return fetchTools().then(function (list) {
            setTools(list);
            notify((!t.enabled ? "Enabled " : "Disabled ") + t.name, "success");
          });
        })
        .catch(function (err) {
          notify("Error: " + String((err && err.message) || err), "error"); // keep old state on error
        })
        .finally(function () {
          setBusy(false);
        });
    }

    function toggleGuardrails(t) {
      if (busy) return; // one PUT at a time — concurrent writes race on the same config key
      setBusy(true);
      setError(null);
      SDK.fetchJSON(API + "/tools/" + encodeURIComponent(t.name) + "/guardrails", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !t.guarded })
      })
        .then(function () {
          return fetchTools().then(function (list) {
            setTools(list);
            notify((t.guarded ? "Ungated " : "Gated ") + t.name, "success");
          });
        })
        .catch(function (err) {
          notify("Error: " + String((err && err.message) || err), "error"); // keep old state on error
        })
        .finally(function () {
          setBusy(false);
        });
    }

    var memo = useMemo(function () {
      var counts = { other: 0 };
      var enabledCount = 0;
      var guardedCount = 0;
      var gateSet = {};
      var i, t, cat;
      for (i = 0; i < CATEGORIES.length; i++) counts[CATEGORIES[i][0]] = 0;
      for (i = 0; i < tools.length; i++) {
        t = tools[i];
        cat = categoryOf(t.name);
        counts[cat] = (counts[cat] || 0) + 1;
        if (t.enabled) enabledCount++;
        if (t.guarded) guardedCount++;
        if (t.gate) gateSet[t.gate] = true;
      }
      var gates = Object.keys(gateSet).sort();
      var q = query.toLowerCase();
      var visible = tools.filter(function (t2) {
        if (gateFilter !== "all" && t2.gate !== gateFilter) return false;
        if (q && (t2.name + " " + (t2.description || "")).toLowerCase().indexOf(q) === -1) return false;
        return true;
      });
      return {
        counts: counts,
        enabledCount: enabledCount,
        guardedCount: guardedCount,
        gates: gates,
        visible: visible
      };
    }, [tools, query, gateFilter]);

    var total = tools.length;
    var ungatedCount = total - memo.guardedCount;

    function toggleControl(props) {
      if (Checkbox) return React.createElement(Checkbox, props);
      // older host without Checkbox: outlined sm Button as the toggle
      return React.createElement(
        Button,
        { size: "sm", outlined: true, onClick: props.onCheckedChange },
        props.checked ? "On" : "Off"
      );
    }

    function toggleExpanded(name) {
      // functional update: survives batched events, no stale-closure overwrite
      setExpanded(function (prev) {
        var next = Object.assign({}, prev);
        next[name] = !prev[name];
        return next;
      });
    }

    /* Code-doc type label for one parameter spec: type, anyOf union, or "any". */
    function paramType(spec) {
      if (!spec || typeof spec !== "object") return "any";
      if (spec.type) return String(spec.type);
      if (Array.isArray(spec.anyOf)) {
        return spec.anyOf
          .map(function (branch) {
            if (branch && Array.isArray(branch.enum)) {
              return branch.enum.map(function (v) { return JSON.stringify(v); }).join(" | ");
            }
            return branch && branch.type ? String(branch.type) : "any";
          })
          .join(" | ");
      }
      return "any";
    }

    /* Doc payload for a row: the live API payload when it carries `parameters`
     * (plugin >= 0.24.0 mounted on the host), else the generated TOOL_DOCS
     * fallback — a host started before that still serves the old GET /tools
     * shape without `parameters`. */
    function docFor(t) {
      if (t && t.parameters && typeof t.parameters === "object") return t;
      var emb = typeof TOOL_DOCS === "object" && TOOL_DOCS && TOOL_DOCS[t.name];
      return emb ? Object.assign({}, t, emb) : t; // keep row fields (name, gate, ...), take doc fields
    }

    /* The exact call signature: required params bare, optional ones rendered as name=default. */
    function signatureOf(t) {
      t = docFor(t);
      var params = (t.parameters && t.parameters.properties) || {};
      var required = (t.parameters && t.parameters.required) || [];
      var names = Object.keys(params);
      if (names.length === 0) return t.name + "()";
      var parts = names.map(function (p) {
        if (required.indexOf(p) !== -1) return p;
        var spec = params[p] || {};
        if (Object.prototype.hasOwnProperty.call(spec, "default")) {
          return p + "=" + JSON.stringify(spec.default);
        }
        return p;
      });
      return t.name + "(" + parts.join(", ") + ")";
    }

    /* Expanded doc panel: full description, the call signature, and the parameter table. */
    function renderDetail(t) {
      t = docFor(t);
      var params = (t.parameters && t.parameters.properties) || {};
      var required = (t.parameters && t.parameters.required) || [];
      var names = Object.keys(params);
      return React.createElement(
        "div",
        { className: "nc-detail" },
        React.createElement("p", { className: "nc-detail-desc" }, t.description || ""),
        React.createElement("code", { className: "nc-signature" }, signatureOf(t)),
        names.length === 0
          ? null
          : React.createElement(
              "table",
              { className: "nc-params" },
              React.createElement(
                "thead",
                null,
                React.createElement(
                  "tr",
                  null,
                  React.createElement("th", null, "Parameter"),
                  React.createElement("th", null, "Type"),
                  React.createElement("th", null, "Required"),
                  React.createElement("th", null, "Default"),
                  React.createElement("th", null, "Description")
                )
              ),
              React.createElement(
                "tbody",
                null,
                names.map(function (p) {
                  var spec = params[p] || {};
                  return React.createElement(
                    "tr",
                    { key: p, className: "nc-param" },
                    React.createElement("td", { className: "nc-param-name" }, p),
                    React.createElement("td", { className: "nc-param-type" }, paramType(spec)),
                    React.createElement("td", null, required.indexOf(p) !== -1 ? "required" : ""),
                    React.createElement(
                      "td",
                      { className: "nc-param-default" },
                      Object.prototype.hasOwnProperty.call(spec, "default") ? JSON.stringify(spec.default) : "—"
                    ),
                    React.createElement("td", { className: "nc-param-desc" }, spec.description || "")
                  );
                })
              )
            )
      );
    }

    function renderRow(t) {
      var isOpen = !!expanded[t.name];
      var row = React.createElement(
        "div",
        { className: "nc-row" },
        // every row expands — even with a missing/empty parameters payload (older
        // plugin_api still mounted on the host), the panel still shows the full
        // description and the bare nc_name() signature
        React.createElement(
          Button,
          {
            size: "sm",
            outlined: true,
            className: "nc-expand",
            "aria-expanded": isOpen ? "true" : "false",
            "aria-label": (isOpen ? "Hide" : "Show") + " details for " + t.name,
            onClick: function () {
              toggleExpanded(t.name);
            }
          },
          isOpen ? "▾" : "▸"
        ),
        toggleControl({
          checked: t.enabled,
          disabled: busy,
          "aria-label": "Enable " + t.name,
          onCheckedChange: function () {
            toggle(t);
          }
        }),
        React.createElement("span", { className: "nc-name", title: t.description || t.name }, t.name),
        React.createElement("span", { className: "nc-desc" }, t.description || ""),
        React.createElement(Badge, { tone: GATE_TONE[t.gate] || "outline" }, t.gate),
        React.createElement(
          "span",
          { className: "nc-gate" },
          "gate",
          toggleControl({
            checked: t.guarded,
            disabled: busy,
            "aria-label": "Approval gate " + t.name,
            onCheckedChange: function () {
              toggleGuardrails(t);
            }
          })
        )
      );
      return React.createElement(
        React.Fragment,
        { key: t.name },
        row,
        isOpen ? renderDetail(t) : null
      );
    }

    function renderTabs() {
      return React.createElement(Tabs, { defaultValue: "all" }, function (active, setActive) {
        var inTab =
          active === "all"
            ? memo.visible
            : memo.visible.filter(function (t) {
                return categoryOf(t.name) === active;
              });
        var triggers = [
          React.createElement(
            TabsTrigger,
            { key: "all", value: "all", active: active === "all", onClick: function () { setActive("all"); } },
            "All (" + total + ")"
          )
        ];
        CATEGORIES.forEach(function (c) {
          if (memo.counts[c[0]] > 0) {
            triggers.push(
              React.createElement(
                TabsTrigger,
                { key: c[0], value: c[0], active: active === c[0], onClick: function () { setActive(c[0]); } },
                c[2] + " (" + memo.counts[c[0]] + ")"
              )
            );
          }
        });
        if (memo.counts.other > 0) {
          triggers.push(
            React.createElement(
              TabsTrigger,
              { key: "other", value: "other", active: active === "other", onClick: function () { setActive("other"); } },
              "Other (" + memo.counts.other + ")"
            )
          );
        }
        return React.createElement(
          React.Fragment,
          null,
          React.createElement(TabsList, { className: "nc-tabslist" }, triggers),
          React.createElement(
            "div",
            { className: "nc-list" },
            inTab.length === 0
              ? React.createElement("p", { className: "nc-empty" }, "No tools match the current filters.")
              : inTab.map(function (t) {
                  return renderRow(t);
                })
          )
        );
      });
    }

    return React.createElement(
      "div",
      { className: cn("flex", "flex-col", "gap-4") },
      toastState ? React.createElement(Toast, { toast: toastState.toast }) : null,
      React.createElement(
        Card,
        null,
        React.createElement(
          CardHeader,
          { className: "flex flex-row flex-wrap items-center justify-between gap-2" },
          React.createElement(CardTitle, null, "Nextcloud tools"),
          React.createElement(
            "div",
            { className: "nc-summary" },
            React.createElement(Badge, { tone: "secondary" }, memo.enabledCount + "/" + total + " enabled"),
            React.createElement(Badge, { tone: "default" }, memo.guardedCount + " gated"),
            React.createElement(
              Badge,
              { tone: ungatedCount ? "warning" : "secondary" },
              ungatedCount + " ungated"
            )
          )
        ),
        React.createElement(
          CardContent,
          null,
          error && !toastState
            ? React.createElement("p", { className: "text-sm text-destructive" }, "Error: " + error)
            : null,
          React.createElement(
            "p",
            { className: "text-sm text-muted-foreground" },
            tools.length +
              " tools. The ▸ button at the start of a row expands it to show the tool's full description, call signature, and parameter table. Each row also has two switches: the left one enables or disables the tool for the agent (applies on the next agent start / plugin reload). The gate switch is the approval gate, on by default — no config entry means enabled; a tool stays gated unless it is listed in `ungated_tools`. While the gate is on, write and destructive calls to the tool ask for your approval before they run (applies immediately); turning it off lets the agent call the tool without an approval prompt."
          ),
          React.createElement(
            "div",
            { className: "nc-toolbar" },
            React.createElement(Input, {
              className: "nc-search",
              placeholder: "Filter tools…",
              value: query,
              "aria-label": "Filter tools",
              onChange: function (e) {
                setQuery(e.target.value);
              }
            }),
            React.createElement(
              Select,
              {
                className: "nc-gatefilter",
                value: gateFilter,
                onValueChange: function (v) {
                  setGateFilter(v);
                }
              },
              React.createElement(SelectOption, { value: "all" }, "All gates"),
              memo.gates.map(function (g) {
                return React.createElement(SelectOption, { key: g, value: g }, g);
              })
            )
          ),
          React.createElement(Separator, null),
          total === 0
            ? React.createElement("p", { className: "nc-empty" }, "Loading tools…")
            : renderTabs()
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("nextcloud-tools", NextcloudToolsPage);
})();
