"""``post_tool_call`` usage-stats observer (in-memory, per gateway process).

Registered as the plugin's ``post_tool_call`` hook (payload per the pinned
Hermes hook contract: ``tool_name``, ``args``, ``result``, ``duration_ms``,
``session_id``, ... — ``post_tool_call`` is in ``VALID_HOOKS`` in
hermes_cli/plugins.py of the pinned Hermes source). The hook is a pure
observer: it returns ``None`` and NEVER raises, so a failure here can never
affect the host or the tool result.

Counts are kept in process memory only (reset on restart) and are exposed to
the dashboard tab via ``dashboard/plugin_api.py`` ``GET /usage``. Only ``nc_*``
tools are counted; results are parsed for ``{"ok": false}`` but the raw result
string is never stored or logged.
"""

from __future__ import annotations

import json
import logging
import threading

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STATS: dict[str, dict] = {}


def observe(tool_name="", result=None, duration_ms=None, **_) -> None:
    """``post_tool_call`` hook: record one nc_* tool call. Never raises; returns None."""
    try:
        name = str(tool_name or "")
        if not name.startswith("nc_"):
            return None
        ok = True
        try:
            payload = json.loads(result) if isinstance(result, str) else None
            if isinstance(payload, dict) and payload.get("ok") is False:
                ok = False
        except Exception:
            pass  # unparseable result still counts as a call, ok unknown -> ok
        try:
            ms = float(duration_ms) if duration_ms is not None else 0.0
        except (TypeError, ValueError):
            ms = 0.0
        with _LOCK:
            entry = _STATS.setdefault(name, {"calls": 0, "ok": 0, "error": 0, "total_ms": 0.0})
            entry["calls"] += 1
            entry["ok" if ok else "error"] += 1
            entry["total_ms"] += ms
        log.debug("usage %s ok=%s %.1fms", name, ok, ms)
    except Exception:
        pass  # observer must never break the host
    return None


def snapshot() -> dict:
    """{"tools": [{tool, calls, ok, error, total_ms, avg_ms}...], "total_calls": int} sorted by calls desc."""
    with _LOCK:
        items = []
        for name, e in _STATS.items():
            calls = e["calls"]
            items.append(
                {
                    "tool": name,
                    "calls": calls,
                    "ok": e["ok"],
                    "error": e["error"],
                    "total_ms": round(e["total_ms"], 1),
                    "avg_ms": round(e["total_ms"] / calls, 1) if calls else 0.0,
                }
            )
        items.sort(key=lambda x: (-x["calls"], x["tool"]))
        return {"tools": items, "total_calls": sum(i["calls"] for i in items)}


def reset() -> None:
    """Clear all counters (tests)."""
    with _LOCK:
        _STATS.clear()
