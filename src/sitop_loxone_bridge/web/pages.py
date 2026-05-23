from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"settings": settings, "active": "dashboard"},
    )


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "config.html",
        {"settings": settings, "active": "config"},
    )
