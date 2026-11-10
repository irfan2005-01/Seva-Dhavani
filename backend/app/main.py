"""FastAPI application entry point."""

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy import inspect

from . import config, models  # noqa: F401 - config loads .env; models registers ORM metadata
from .database import Base, SessionLocal, engine
from .seed import seed_database
from .followups import run_followup_job
from datetime import datetime, timezone


async def _followup_loop():
    while True:
        await asyncio.sleep(config.FOLLOWUP_INTERVAL_SECONDS)
        try:
            with SessionLocal() as db:
                run_followup_job(db, datetime.now(timezone.utc))
        except Exception:
            import logging
            logging.getLogger("seva_dhwani.followups").exception("Scheduled follow-up run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Additive migrations preserve existing complaint data.
    existing_columns = {column["name"] for column in inspect(engine).get_columns("complaints")}
    with engine.begin() as connection:
        for column_name in ("transcript_original", "summary_english"):
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE complaints ADD COLUMN {column_name} TEXT"))
        if "escalation_level" not in existing_columns:
            connection.execute(text("ALTER TABLE complaints ADD COLUMN escalation_level INTEGER NOT NULL DEFAULT 0"))
    if "notifications" in inspect(engine).get_table_names():
        notification_columns = {column["name"] for column in inspect(engine).get_columns("notifications")}
        if "dedupe_key" not in notification_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN dedupe_key VARCHAR(180)"))
        with engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_notifications_dedupe_key ON notifications (dedupe_key)"))
    with SessionLocal() as db:
        seed_database(db)
    app.state.followup_task = asyncio.create_task(_followup_loop())
    yield
    app.state.followup_task.cancel()
    try:
        await app.state.followup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Seva Dhwani API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers.complaints import router as complaints_router
from .routers.hospitals import router as hospitals_router
from .routers.voice import router as voice_router
from .routers.followups import router as followups_router
from .routers.stats import router as stats_router
from .routers.channels import router as channels_router

app.include_router(complaints_router)
app.include_router(hospitals_router)
app.include_router(voice_router)
app.include_router(followups_router)
app.include_router(stats_router)
app.include_router(channels_router)

@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "Seva Dhwani", "database": "connected"}


from pathlib import Path
from fastapi.staticfiles import StaticFiles

@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "dashboard.html")


@app.get("/assisted", include_in_schema=False)
def assisted_page():
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "assisted.html")


@app.get("/ivr", include_in_schema=False)
def ivr_page():
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "ivr.html")


@app.get("/sms", include_in_schema=False)
def sms_page():
    if not config.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Phone inbox simulation is available only in demo mode")
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "sms.html")

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="frontend")
