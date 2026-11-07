"""Dashboard-side store for per-tool enable/disable (stdlib only).

Tool names come from plugin.yaml via regex — no yaml import, so the test venv
(httpx + pytest only) can import this module. The on-disk location in
~/.hermes/config.yaml is ``plugins.entries.nextcloud-tools.settings.disabled_tools``:
a sorted list of tool names that ``register()`` leaves unregistered.
"""

from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_TOOL_RE = re.compile(r"^  - (nc_\w+)$", re.M)

_SETTINGS_PATH = ("plugins", "entries", "nextcloud-tools", "settings")
_DISABLED_KEY = "disabled_tools"


def list_tool_names() -> list[str]:
    """The nc_* tool names from plugin.yaml's provides_tools, in manifest order."""
    text = (PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8")
    return _TOOL_RE.findall(text)


def get_disabled_tools(config: dict) -> list[str]:
    """The configured disabled_tools list; [] when any section is missing or wrong-typed."""
    node = config
    for key in (*_SETTINGS_PATH, _DISABLED_KEY):
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    if not isinstance(node, list):
        return []
    return [str(t) for t in node]


def set_tool_enabled(config: dict, name: str, enabled: bool) -> list[str]:
    """Add/remove ``name`` in the config's disabled_tools list (kept sorted).

    Validates ``name`` against list_tool_names() BEFORE mutating config, creates
    missing nested sections, and returns the new list. Never writes any file —
    persistence is the caller's job. Raises ValueError for an unknown tool name.
    """
    if name not in list_tool_names():
        raise ValueError(f"unknown nc_* tool: {name!r}")
    node = config
    for key in _SETTINGS_PATH:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    raw = node.get(_DISABLED_KEY)
    disabled = {str(t) for t in raw} if isinstance(raw, list) else set()
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    new_list = sorted(disabled)
    node[_DISABLED_KEY] = new_list
    return new_list


def classify_gate(name: str) -> str:
    """Static gate label: 'read' | 'write' | 'destructive' | 'mixed'.

    nc_comments / nc_ocs gate on their args (action / method), so anything not
    in the three static sets reports 'mixed'.
    """
    from .guardrails import DESTRUCTIVE, READ_ONLY, WRITES

    if name in READ_ONLY:
        return "read"
    if name in WRITES:
        return "write"
    if name in DESTRUCTIVE:
        return "destructive"
    return "mixed"
