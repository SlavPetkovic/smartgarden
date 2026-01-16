from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from smartgarden.web.routes import router as routes_router
from smartgarden.web.api import router as api_router, legacy_router
from smartgarden.web.analytics_api import router as analytics_router


def create_app() -> FastAPI:
    app = FastAPI(title="SmartGarden")

    app.mount(
        "/static",
        StaticFiles(directory="src/smartgarden/web/static"),
        name="static",
    )

    app.include_router(routes_router)
    app.include_router(api_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api/analytics")
    app.include_router(legacy_router)

    return app


app = create_app()
