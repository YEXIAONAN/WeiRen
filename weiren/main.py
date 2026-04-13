from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from weiren.config import settings
from weiren.db import init_db
from weiren.routes import router


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title=settings.app_title)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.include_router(router)
    return app


app = create_app()
