"""Dashboard-side store for per-tool toggles (stdlib only).

Tool names come from plugin.yaml via regex — no yaml import, so the test venv
(httpx + pytest only) can import this module. The on-disk location in
~/.hermes/config.yaml is ``plugins.entries.nextcloud-tools.settings`` with two
sorted list keys:

- ``disabled_tools``: tool names that ``register()`` leaves unregistered.
- ``ungated_tools``: tool names exempt from the pre_tool_call approval gate
  (``guardrails.guard()`` returns None for them; read per call).
"""

from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_TOOL_RE = re.compile(r"^  - (nc_\w+)$", re.M)

_SETTINGS_PATH = ("plugins", "entries", "nextcloud-tools", "settings")
_DISABLED_KEY = "disabled_tools"
_UNGATED_KEY = "ungated_tools"


def _settings_node(config: dict, create: bool = False):
    """The ``settings`` dict inside config, or None when a section is missing/wrong-typed.

    With ``create=True`` missing or wrong-typed sections are replaced by fresh
    dicts so the caller can mutate in place.
    """
    node = config
    for key in _SETTINGS_PATH:
        if not isinstance(node, dict):
            return None
        child = node.get(key)
        if not isinstance(child, dict):
            if not create:
                return None
            child = {}
            node[key] = child
        node = child
    return node if isinstance(node, dict) else None


def _get_str_list(config: dict, key: str) -> list[str]:
    """The list stored under ``key`` in the settings node; [] when missing or wrong-typed."""
    node = _settings_node(config)
    if node is None:
        return []
    raw = node.get(key)
    if not isinstance(raw, list):
        return []
    return [str(t) for t in raw]


def _set_str_list(config: dict, key: str, name: str, present: bool) -> list[str]:
    """Add/remove ``name`` in the settings list under ``key`` (kept sorted).

    Validates ``name`` against list_tool_names() BEFORE mutating config, creates
    missing nested sections, and returns the new list. Never writes any file —
    persistence is the caller's job. Raises ValueError for an unknown tool name.
    """
    if name not in list_tool_names():
        raise ValueError(f"unknown nc_* tool: {name!r}")
    node = _settings_node(config, create=True)
    raw = node.get(key)
    items = {str(t) for t in raw} if isinstance(raw, list) else set()
    if present:
        items.add(name)
    else:
        items.discard(name)
    new_list = sorted(items)
    node[key] = new_list
    return new_list


def list_tool_names() -> list[str]:
    """The nc_* tool names from plugin.yaml's provides_tools, in manifest order."""
    text = (PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8")
    return _TOOL_RE.findall(text)


def tool_doc(name: str) -> dict:
    """The doc payload for one tool, read live from ``schemas`` (single source of truth).

    Returns ``{"description": str, "parameters": dict}`` where ``parameters`` is the
    tool schema's ``parameters`` object (type/properties/required) — the same dict
    the agent-facing registration uses, looked up by the ``nc_x`` -> ``NC_X`` naming
    convention. Unknown names or malformed schemas get an empty doc shape so callers
    can render defensively.
    """
    from . import schemas

    empty = {"type": "object", "properties": {}, "required": []}
    schema = getattr(schemas, name.upper(), None)
    if not isinstance(schema, dict):
        return {"description": "", "parameters": empty}
    parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        parameters = empty
    return {"description": str(schema.get("description") or ""), "parameters": parameters}


def get_disabled_tools(config: dict) -> list[str]:
    """The configured disabled_tools list; [] when any section is missing or wrong-typed."""
    return _get_str_list(config, _DISABLED_KEY)


def get_ungated_tools(config: dict) -> list[str]:
    """The configured ungated_tools list; [] when any section is missing or wrong-typed."""
    return _get_str_list(config, _UNGATED_KEY)


def set_tool_enabled(config: dict, name: str, enabled: bool) -> list[str]:
    """Add/remove ``name`` in the config's disabled_tools list (kept sorted).

    Validates ``name`` against list_tool_names() BEFORE mutating config, creates
    missing nested sections, and returns the new list. Never writes any file —
    persistence is the caller's job. Raises ValueError for an unknown tool name.
    """
    return _set_str_list(config, _DISABLED_KEY, name, not enabled)


def set_tool_guarded(config: dict, name: str, guarded: bool) -> list[str]:
    """Add/remove ``name`` in the config's ungated_tools list (kept sorted).

    ``guarded=False`` puts ``name`` in ungated_tools (exempt from the approval
    gate). Same validation and no-file-write contract as set_tool_enabled.
    """
    return _set_str_list(config, _UNGATED_KEY, name, not guarded)


def classify_gate(name: str) -> str:
    """Static gate label: 'read' | 'write' | 'destructive' | 'mixed'.

    nc_ocs gates on its method arg, so anything not in the three static
    sets reports 'mixed'.
    """
    from .guardrails import DESTRUCTIVE, READ_ONLY, WRITES

    if name in READ_ONLY:
        return "read"
    if name in WRITES:
        return "write"
    if name in DESTRUCTIVE:
        return "destructive"
    return "mixed"
