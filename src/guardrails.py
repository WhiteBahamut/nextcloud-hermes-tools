"""``pre_tool_call`` guardrail hook.

Classification via three frozensets (``nc_comments`` dispatches on
``args["action"]``; ``nc_ocs`` gates GET as read, DELETE as destructive and other
non-GET methods as writes):

- READ_ONLY -> ``None`` (normal approval policy applies)
- WRITES -> ``{"action": "approve", ...}`` — escalates to the human approval gate
- DESTRUCTIVE -> ``approve`` with rule_key ``nc-destructive``, or ``block`` when
  settings ``hard_block_destructive`` is true

Gated calls also carry a plain-English summary of what they do (``_SUMMARIES``
/``_ACTION_SUMMARIES`` templates rendered by ``_describe``) in the approval
``message`` — action + target instead of a raw arg value — redacted before
return so no secret leaks into the prompt.


The hook NEVER raises (a raise fails closed and would block every tool): on any
internal error an ``nc_`` tool is routed to ``approve`` (fail toward the gate),
anything else returns ``None``. Non-``nc_`` tools always return ``None``.
"""

from __future__ import annotations

import base64
import logging

from . import client

log = logging.getLogger(__name__)

READ_ONLY = frozenset({
    "nc_file_list", "nc_file_get", "nc_search", "nc_file_search", "nc_share_list",
    "nc_talk_rooms", "nc_talk_messages", "nc_cal_list", "nc_cal_list_calendars", "nc_task_list",
    "nc_contact_list", "nc_contact_list_books", "nc_contact_search", "nc_contact_get", "nc_note_list",
    "nc_note_get", "nc_activity", "nc_notifications", "nc_tag_list", "nc_trash_list",
})

WRITES = frozenset({
    "nc_file_put", "nc_file_mkdir", "nc_file_move", "nc_file_copy", "nc_share_create", "nc_share_edit",
    "nc_talk_send", "nc_talk_react", "nc_cal_create", "nc_cal_edit",
    "nc_task_create", "nc_task_complete", "nc_task_reopen", "nc_contact_create", "nc_contact_edit",
    "nc_note_create", "nc_note_edit", "nc_tag_assign", "nc_tag_unassign",
    "nc_trash_restore",
})

DESTRUCTIVE = frozenset({
    "nc_file_delete", "nc_share_delete", "nc_talk_delete", "nc_cal_delete",
    "nc_note_delete", "nc_trash_empty",
})

_BRIEF_KEYS = ("path", "source", "destination", "token", "trash_path", "uid", "id", "term")


def _brief(args) -> str:
    for key in _BRIEF_KEYS:
        value = (args or {}).get(key)
        if value:
            return str(value)[:200]
    return ""

# Plain-English approval summaries, one template per gated tool. Placeholders
# are schema arg names (src/schemas.py); _describe renders them safely.
_SUMMARIES = {
    "nc_file_put": "create or overwrite file '{path}' ({size} bytes)",
    "nc_file_mkdir": "create folder '{path}'",
    "nc_file_move": "move '{source}' to '{destination}'",
    "nc_file_copy": "copy '{source}' to '{destination}'",
    "nc_file_delete": "delete '{path}' (moves to trashbin)",
    "nc_share_create": "share '{path}' with '{share_with}' (type {share_type}, permissions {permissions})",
    "nc_share_edit": "edit share {id} ({fields})",
    "nc_share_delete": "delete share with id {id}",
    "nc_talk_send": "send message to room {token}: '{message}'",
    "nc_talk_delete": "delete message id {message_id} in room {token}",
    "nc_talk_react": "{react} reaction '{emoji}' on message id {message_id} in room {token}",
    "nc_cal_create": "create event '{summary}' in calendar '{calendar}' ({start} to {end})",
    "nc_cal_edit": "edit event with uid '{uid}' in calendar '{calendar}'",
    "nc_cal_delete": "delete event with uid '{uid}' in calendar '{calendar}'",
    "nc_task_create": "create task '{summary}' in list '{calendar}'",
    "nc_task_complete": "mark task with uid '{uid}' in '{calendar}' completed",
    "nc_task_reopen": "reopen task with uid '{uid}' in '{calendar}'",
    "nc_contact_create": "create contact '{fn}' in address book '{book}'",
    "nc_contact_edit": "edit contact with uid '{uid}' in address book '{book}'",
    "nc_note_create": "create note '{title}'",
    "nc_note_edit": "edit note with id '{id}'",
    "nc_note_delete": "delete note with id '{id}'",
    "nc_tag_assign": "assign tag '{tag}' to '{path}'",
    "nc_tag_unassign": "remove tag '{tag}' from '{path}'",
    "nc_trash_restore": "restore trashbin entry '{trash_path}' to its original location",
    "nc_trash_empty": "empty the ENTIRE trashbin",
}

# Arg-dispatched tools: template chosen via args["action"] / args["method"],
# exactly like _classify. nc_ocs "*" is the fallback for any non-GET method;
# nc_comments' {file_target} is computed in _describe as file_id else path.
_ACTION_SUMMARIES = {
    "nc_comments": {
        "add": "add comment '{message}' on file {file_target}",
        "delete": "delete comment id {comment_id} on file {file_target}",
    },
    "nc_ocs": {
        "DELETE": "DELETE /ocs/v2.php/{path} (destructive)",
        "*": "{method} /ocs/v2.php/{path}",
    },
}


# Schema defaults the handlers apply when the arg is omitted, so the summary
# reflects what the call will actually do (calendar -> personal/tasks, book -> contacts).
_ARG_DEFAULTS = {
    "nc_cal_create": {"calendar": "personal"},
    "nc_task_create": {"calendar": "tasks"},
    "nc_task_complete": {"calendar": "tasks"},
    "nc_task_reopen": {"calendar": "tasks"},
    "nc_contact_create": {"book": "contacts"},
    "nc_contact_edit": {"book": "contacts"},
}


class _SafeDict(dict):
    """format_map mapping that renders missing keys as empty strings."""

    def __missing__(self, _key):
        return ""


def _trunc(value, limit: int = 120) -> str:
    text = str(value)
    return text[:limit] + "…" if len(text) > limit else text


def _describe(name: str, args) -> str:
    """Plain-English summary of a gated call; unknown tools fall back to '<name> <brief>'."""
    a = args or {}
    template = _SUMMARIES.get(name)
    extra = {}
    if name == "nc_comments":
        template = _ACTION_SUMMARIES["nc_comments"].get(str(a.get("action") or "list"))
        extra["file_target"] = a.get("file_id") or a.get("path") or ""
    elif name == "nc_ocs":
        method = str(a.get("method") or "GET").upper()
        template = _ACTION_SUMMARIES["nc_ocs"].get(method, _ACTION_SUMMARIES["nc_ocs"]["*"])
        extra["method"] = method
    elif name == "nc_talk_react":
        extra["react"] = "add" if a.get("react", True) else "remove"
    elif name == "nc_file_put":
        try:
            if a.get("content_base64"):
                size = len(base64.b64decode(a["content_base64"]))
            else:
                size = len(a.get("content") or "")
        except Exception:
            size = 0
        extra["size"] = size
        if size == 0 and a.get("allow_empty"):
            template = "create or overwrite file '{path}' ({size} bytes, empty file)"
    elif name == "nc_share_edit":
        fields = []
        for k in ("permissions", "password", "expire_date", "note"):
            if k in a:
                fields.append(f"{k}=***" if k == "password" else f"{k}={a[k]}")
        extra["fields"] = ", ".join(fields) or "no fields"

    elif name == "nc_note_edit" and str(a.get("title") or ""):
        template = "edit note '{title}' (id {id})"
    elif name == "nc_contact_edit" and str(a.get("fn") or ""):
        template = "edit contact '{fn}' (uid {uid}) in address book '{book}'"
    if template is None:
        return f"{name} {_brief(a)}"
    values = {k: _trunc(v) for k, v in a.items()}
    values.update({k: _trunc(v) for k, v in extra.items()})
    for key, default in _ARG_DEFAULTS.get(name, {}).items():
        if not values.get(key):
            values[key] = default
    return template.format_map(_SafeDict(values))


def _gated_message(prefix: str, name: str, summary: str) -> str:
    """'<prefix> — <summary> (<name>)' capped at 280 chars (summary truncated)."""
    head, tail = f"{prefix} — ", f" ({name})"
    budget = 280 - len(head) - len(tail)
    if len(summary) > budget:
        summary = summary[: max(budget - 1, 0)] + "…"
    return f"{head}{summary}{tail}"


def _classify(tool_name: str, args) -> str | None:
    """'read' | 'write' | 'destructive' | None (passthrough)."""
    if tool_name in READ_ONLY:
        return "read"
    if tool_name in WRITES:
        return "write"
    if tool_name in DESTRUCTIVE:
        return "destructive"
    if tool_name == "nc_comments":
        action = str((args or {}).get("action") or "list")
        if action == "list":
            return "read"
        return "destructive" if action == "delete" else "write"
    if tool_name == "nc_ocs":
        m = str((args or {}).get("method") or "GET").upper()
        if m == "GET":
            return "read"
        return "destructive" if m == "DELETE" else "write"
    return None


def guard(tool_name="", args=None, **_):
    try:
        name = tool_name or ""
        if not name.startswith("nc_"):
            return None
        cls = _classify(name, args)
        log.debug("guard %s -> %s", name, cls)
        if cls == "read" or cls is None:
            return None
        summary = client.redact(_describe(name, args))
        if cls == "destructive":
            if client.settings()["hard_block_destructive"]:
                log.warning("hard-block destructive %s %s", name, summary)
                return {
                    "action": "block",
                    "message": _gated_message("Destructive Nextcloud op hard-blocked (hard_block_destructive)", name, summary),
                    "rule_key": "nc-destructive",
                }
            return {
                "action": "approve",
                "message": _gated_message("Destructive Nextcloud op", name, summary),
                "rule_key": "nc-destructive",
            }
        return {
            "action": "approve",
            "message": _gated_message("Nextcloud write", name, summary),
            "rule_key": "nc-write",
        }
    except Exception as exc:
        # fail toward the gate for nc_ tools; never raise (a raise blocks everything)
        try:
            if str(tool_name or "").startswith("nc_"):
                return {
                    "action": "approve",
                    "message": client.redact(f"Nextcloud guardrail error, routing {tool_name} to approval: {exc}"),
                    "rule_key": "nc-error",
                }
        except Exception:
            pass
        return None
