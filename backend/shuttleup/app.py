from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .auth.routes import router as auth_router
from .auth.settings_routes import router as settings_router
from .activities.routes import router as activities_router
from .activities.workflow_routes import router as workflow_router
from .availability.routes import router as availability_router
from .availability.import_routes import router as import_router
from .realtime.routes import router as realtime_router
from .realtime.web_routes import router as realtime_web_router
from .billing.routes import router as billing_router
from .venues.routes import router as venues_router
from .integrations.routes import web_router as bot_web_router, bot_router
from .config import get_settings
from .db import Base, engine
from . import models  # noqa: F401
from .realtime.background import event_worker, venue_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    stop = asyncio.Event()
    tasks = [asyncio.create_task(event_worker(stop)), asyncio.create_task(venue_worker(stop))]
    yield
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="ShuttleUp API", version="1.0.0", lifespan=lifespan)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(activities_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(availability_router, prefix="/api/v1")
app.include_router(import_router, prefix="/api/v1")
app.include_router(realtime_router, prefix="/api/v1")
app.include_router(realtime_web_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(venues_router, prefix="/api/v1")
app.include_router(bot_web_router, prefix="/api/v1")
app.include_router(bot_router, prefix="/bot/v1")


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请检查输入内容。", "details": exc.errors()}})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready"}


static_dir = get_settings().static_dir
if static_dir.exists():
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        requested = static_dir / path
        if path and requested.is_file():
            return FileResponse(requested)
        index = static_dir / "index.html"
        return FileResponse(index) if index.exists() else JSONResponse({"message": "Frontend not built"}, status_code=404)
