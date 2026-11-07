"""``pre_tool_call`` guardrail hook.

Classification via three frozensets (``nc_comments`` dispatches on
``args["action"]``; ``nc_ocs`` gates POST as a write, GET passes through):

- READ_ONLY -> ``None`` (normal approval policy applies)
- WRITES -> ``{"action": "approve", ...}`` — escalates to the human approval gate
- DESTRUCTIVE -> ``approve`` with rule_key ``nc-destructive``, or ``block`` when
  settings ``hard_block_destructive`` is true

The hook NEVER raises (a raise fails closed and would block every tool): on any
internal error an ``nc_`` tool is routed to ``approve`` (fail toward the gate),
anything else returns ``None``. Non-``nc_`` tools always return ``None``.
"""

from __future__ import annotations

from . import client

READ_ONLY = frozenset({
    "nc_file_list", "nc_file_get", "nc_search", "nc_file_search", "nc_share_list",
    "nc_talk_rooms", "nc_talk_messages", "nc_cal_list", "nc_task_list",
    "nc_contact_list", "nc_contact_search", "nc_contact_get", "nc_note_list",
    "nc_note_get", "nc_activity", "nc_notifications", "nc_tag_list", "nc_trash_list",
})

WRITES = frozenset({
    "nc_file_put", "nc_file_mkdir", "nc_file_move", "nc_share_create",
    "nc_talk_send", "nc_talk_react", "nc_cal_create", "nc_cal_edit",
    "nc_task_create", "nc_task_complete", "nc_contact_create", "nc_contact_edit",
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
        return "read" if str((args or {}).get("method") or "GET").upper() == "GET" else "write"
    return None


def guard(tool_name="", args=None, **_):
    try:
        name = tool_name or ""
        if not name.startswith("nc_"):
            return None
        cls = _classify(name, args)
        if cls == "read" or cls is None:
            return None
        brief = _brief(args)
        if cls == "destructive":
            if client.settings()["hard_block_destructive"]:
                return {
                    "action": "block",
                    "message": f"Destructive Nextcloud op hard-blocked (hard_block_destructive): {name} {brief}".strip(),
                    "rule_key": "nc-destructive",
                }
            return {
                "action": "approve",
                "message": f"Destructive Nextcloud op: {name} {brief}".strip(),
                "rule_key": "nc-destructive",
            }
        return {
            "action": "approve",
            "message": f"Nextcloud write: {name} {brief}".strip(),
            "rule_key": "nc-write",
        }
    except Exception as exc:
        # fail toward the gate for nc_ tools; never raise (a raise blocks everything)
        try:
            if str(tool_name or "").startswith("nc_"):
                return {
                    "action": "approve",
                    "message": f"Nextcloud guardrail error, routing {tool_name} to approval: {exc}",
                    "rule_key": "nc-error",
                }
        except Exception:
            pass
        return None
