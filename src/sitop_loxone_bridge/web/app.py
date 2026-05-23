from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sitop_loxone_bridge.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="SITOP → Loxone Bridge", version="0.2.0")
    app.state.settings = settings
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    here = Path(__file__).parent
    app.state.templates = Jinja2Templates(directory=str(here / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(here / "static")),
        name="static",
    )

    from sitop_loxone_bridge.web import api, pages

    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")
    return app
