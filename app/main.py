import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import router as api_router
from app.core.cors import CORS_ORIGINS
from app.core.cache import redis_is_available
from app.core.database import SessionLocal
from app.core.exception_handlers import register_exception_handlers
from app.core.logging_config import configure_logging
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.seeds.seed_super_admin import ensure_super_admin

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Lebanon News Monitor API")
register_exception_handlers(app)


@app.middleware("http")
async def assign_login_device(request: Request, call_next):
    device_id = request.cookies.get("login_device_id") or secrets.token_urlsafe(32)
    request.state.login_device_id = device_id
    response = await call_next(request)
    if "login_device_id" not in request.cookies:
        response.set_cookie(
            key="login_device_id",
            value=device_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=False,
            samesite="lax",
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.on_event("startup")
def startup() -> None:
    db = SessionLocal()
    try:
        ensure_super_admin(db)
        from app.news.services.pipeline_advisory_lock import (
            reclaim_stale_pipeline_advisory_locks,
        )

        terminated = reclaim_stale_pipeline_advisory_locks(
            db,
            reclaim_other_workers=False,
        )
        if terminated:
            logger.warning(
                "Backend startup reclaimed %s stale pipeline advisory lock(s)",
                terminated,
            )
    finally:
        db.close()
    # Docker runs a dedicated red-alert-collector service. Starting another
    # collector inside the API duplicates ingestion runs and makes one batch
    # appear as multiple log rows.
    start_scheduler(start_red_alert=False)


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    database_status = "ok"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database readiness check failed")
        database_status = "unavailable"
    finally:
        db.close()

    redis_status = "ok" if redis_is_available() else "unavailable"
    return {
        "status": "ok" if database_status == "ok" and redis_status == "ok" else "degraded",
        "database": database_status,
        "redis": redis_status,
    }
