"""Dashboard plugin API for nextcloud-tools — runs inside the Hermes dashboard host only.

Mounted at ``/api/plugins/nextcloud-tools/``. Never imported by the CLI plugin or
the test suite: fastapi / hermes_cli are host-only dependencies.

Wire contract with ``dist/index.js`` (never rename one side only):
  GET /tools            -> {"tools": [{"name", "description", "parameters", "gate", "enabled", "guarded"}]}
  PUT /tools/{name}     -> {"ok": true, "disabled_tools": [...]}  (body {"enabled": bool})
  PUT /tools/{name}/guardrails -> {"ok": true, "ungated_tools": [...]}  (body {"enabled": bool})
  Errors: 400 unknown tool / schema mismatch, 403 managed install or
  administrator-managed key (host-only — the mock never returns these).
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
PLUGIN_ID = "nextcloud-tools"

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

from nextcloud_tools import dashboard_store  # noqa: E402

# Same profile-scoped seam as hermes_cli/web_routers/tools.py: _profile_scope
# for reads, config_write_scope (= _profile_scope + _CONFIG_MUTATION_LOCK) for
# writes. Writes go through hermes_cli.plugins_settings.save_plugin_settings —
# the canonical plugin-settings writer (the same one ctx.set_config uses) — so
# config_schema validation applies and managed-install / administrator-managed-key
# refusals surface as PermissionError -> 403. The whole config dict is never saved.
from hermes_cli.config import load_config  # noqa: E402
from hermes_cli.plugins_settings import save_plugin_settings  # noqa: E402
from hermes_cli.web_routers._common import _profile_scope, config_write_scope  # noqa: E402

router = APIRouter()


class ToolToggle(BaseModel):
    enabled: bool


class GuardrailToggle(BaseModel):
    enabled: bool


@router.get("/tools")
async def list_tools(profile: Optional[str] = None):
    def _read():
        with _profile_scope(profile):
            config = load_config()
            disabled = set(dashboard_store.get_disabled_tools(config))
            ungated = set(dashboard_store.get_ungated_tools(config))
            return {
                "tools": [
                    {
                        "name": name,
                        "gate": dashboard_store.classify_gate(name),
                        "enabled": name not in disabled,
                        "guarded": name not in ungated,
                        **dashboard_store.tool_doc(name),  # description + parameters, live from schemas
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
                save_plugin_settings(PLUGIN_ID, PLUGIN_ROOT, {"disabled_tools": disabled})
            except ValueError as exc:  # unknown tool name or config_schema mismatch
                raise HTTPException(status_code=400, detail=str(exc))
            except PermissionError as exc:  # managed install / administrator-managed key
                raise HTTPException(status_code=403, detail=str(exc))
            return {"ok": True, "disabled_tools": disabled}

    return await asyncio.to_thread(_run)


@router.put("/tools/{name}/guardrails")
async def toggle_guardrails(name: str, body: GuardrailToggle, profile: Optional[str] = None):
    def _run():
        with config_write_scope(profile):
            config = load_config()
            try:
                ungated = dashboard_store.set_tool_guarded(config, name, body.enabled)
                save_plugin_settings(PLUGIN_ID, PLUGIN_ROOT, {"ungated_tools": ungated})
            except ValueError as exc:  # unknown tool name or config_schema mismatch
                raise HTTPException(status_code=400, detail=str(exc))
            except PermissionError as exc:  # managed install / administrator-managed key
                raise HTTPException(status_code=403, detail=str(exc))
            return {"ok": True, "ungated_tools": ungated}

    return await asyncio.to_thread(_run)
