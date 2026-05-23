from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from sitop_loxone_bridge import opcua_discovery
from sitop_loxone_bridge.app_config import (
    AppConfig,
    load_app_config,
    save_app_config,
)
from sitop_loxone_bridge.config import Settings
from sitop_loxone_bridge.loxone_export import render_loxone_template
from sitop_loxone_bridge.runtime_state import load_state
from sitop_loxone_bridge.selection import (
    SelectedParameter,
    Selection,
    load_selection,
    save_selection,
)

log = structlog.get_logger(__name__)
router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


@router.post("/scan")
async def scan(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    cfg = load_app_config(settings.app_config_path, fallback=settings)
    try:
        tree = await opcua_discovery.discover(
            url=cfg.opcua_url,
            username=cfg.opcua_username,
            password=cfg.opcua_password,
            session_timeout_ms=cfg.opcua_session_timeout_ms,
        )
    except Exception as exc:
        log.error("scan.failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"OPC UA scan failed: {exc}")

    return {
        "opcua_url": tree.opcua_url,
        "product_name": tree.product_name,
        "firmware": tree.firmware,
        "modules": [
            {
                "name": m.name,
                "kind": m.kind,
                "path": m.path,
                "active": m.active,
                "parameters": [
                    {
                        "node_id": p.node_id,
                        "browse_name": p.browse_name,
                        "path": p.path,
                        "dtype": p.dtype,
                        "unit": p.unit,
                        "min": p.min,
                        "max": p.max,
                        "value": p.value,
                        "is_status": p.is_status,
                        "sources": p.sources,
                        "aggregation": p.aggregation,
                        "suggested_vi": _suggested_vi_name(m.name, p.browse_name),
                    }
                    for p in m.parameters
                ],
            }
            for m in tree.modules
        ],
    }


def _suggested_vi_name(module_name: str, browse_name: str) -> str:
    if module_name == "Computed":
        if browse_name == "TotalOutputPower":
            return "SITOP_Power"
        return f"SITOP_{browse_name}"
    short_module = module_name.replace("Output", "Out").replace("8600_", "")
    return f"SITOP_{short_module}_{browse_name}"


class SaveSelectionPayload(BaseModel):
    parameters: list[SelectedParameter]


@router.get("/selection")
async def get_selection(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    sel = load_selection(settings.selection_path)
    if sel is None:
        return {"exists": False, "parameters": []}
    return {
        "exists": True,
        "version": sel.version,
        "opcua_url": sel.opcua_url,
        "generated_at": sel.generated_at.isoformat(),
        "parameters": [p.model_dump() for p in sel.parameters],
    }


@router.put("/selection")
async def put_selection(
    request: Request, payload: SaveSelectionPayload
) -> dict[str, Any]:
    settings = _settings(request)
    sel = Selection(
        opcua_url=settings.opcua_url,
        generated_at=datetime.now(UTC),
        parameters=payload.parameters,
    )
    save_selection(settings.selection_path, sel)
    log.info("selection.saved", parameters=len(sel.parameters))
    return {"saved": True, "parameters": len(sel.parameters)}


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    state = load_state(settings.state_path)
    return state.model_dump(mode="json")


@router.get("/config")
async def get_app_config(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    cfg = load_app_config(settings.app_config_path, fallback=settings)
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_app_config(
    request: Request, payload: AppConfig
) -> dict[str, Any]:
    settings = _settings(request)
    save_app_config(settings.app_config_path, payload)
    log.info(
        "config.saved",
        opcua_url=payload.opcua_url,
        loxone_host=payload.loxone_host,
    )
    return {"saved": True}


@router.get("/export.xml")
async def export_xml(request: Request) -> Response:
    settings = _settings(request)
    sel = load_selection(settings.selection_path)
    if sel is None or not sel.parameters:
        raise HTTPException(
            status_code=404,
            detail="No selection has been saved yet.",
        )
    xml = render_loxone_template(sel)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": (
                'attachment; filename="sitop_loxone_template.xml"'
            )
        },
    )
