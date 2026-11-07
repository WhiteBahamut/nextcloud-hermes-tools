"""Dashboard plugin API for nextcloud-tools — runs inside the Hermes dashboard host only.

Mounted at ``/api/plugins/nextcloud-tools/``. Never imported by the CLI plugin or
the test suite: fastapi / hermes_cli are host-only dependencies.

Wire contract with ``dist/index.js`` (never rename one side only):
  GET /tools            -> {"tools": [{"name", "description", "gate", "enabled"}]}
  PUT /tools/{name}     -> {"ok": true, "disabled_tools": [...]}  (body {"enabled": bool})
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Load the plugin package the same way the repo root expects, so the relative
# import in dashboard_store (from .guardrails import ...) resolves when this
# file is loaded by the dashboard host via importlib.
if "nextcloud_tools" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "nextcloud_tools",
        PLUGIN_ROOT / "src" / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT / "src")],
    )
    _pkg = importlib.util.module_from_spec(_spec)
    sys.modules["nextcloud_tools"] = _pkg
    _spec.loader.exec_module(_pkg)

from nextcloud_tools import dashboard_store, schemas  # noqa: E402

# Same profile-scoped read/write seam as hermes_cli/web_routers/tools.py:
# _profile_scope for reads, config_write_scope (= _profile_scope +
# _CONFIG_MUTATION_LOCK) for read-modify-write.
from hermes_cli.config import load_config, save_config  # noqa: E402
from hermes_cli.web_routers._common import _profile_scope, config_write_scope  # noqa: E402

router = APIRouter()


class ToolToggle(BaseModel):
    enabled: bool


def _description(name: str) -> str:
    """Schema description for a tool name (nc_file_list -> schemas.NC_FILE_LIST)."""
    schema = getattr(schemas, name.upper(), None)
    if isinstance(schema, dict):
        return str(schema.get("description") or "")
    return ""


@router.get("/tools")
async def list_tools(profile: Optional[str] = None):
    def _read():
        with _profile_scope(profile):
            config = load_config()
            disabled = set(dashboard_store.get_disabled_tools(config))
            return {
                "tools": [
                    {
                        "name": name,
                        "description": _description(name),
                        "gate": dashboard_store.classify_gate(name),
                        "enabled": name not in disabled,
                    }
                    for name in dashboard_store.list_tool_names()
                ]
            }

    return await asyncio.to_thread(_read)


@router.put("/tools/{name}")
async def toggle_tool(name: str, body: ToolToggle, profile: Optional[str] = None):
    def _run():
        with config_write_scope(profile):
            config = load_config()
            try:
                disabled = dashboard_store.set_tool_enabled(config, name, body.enabled)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            save_config(config)
            return {"ok": True, "disabled_tools": disabled}

    return await asyncio.to_thread(_run)
