import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router as api_router
from app.core.cors import CORS_ORIGINS
from app.core.database import SessionLocal
from app.core.exception_handlers import register_exception_handlers
from app.core.logging_config import configure_logging
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.seeds.seed_super_admin import ensure_super_admin

configure_logging()

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
    finally:
        db.close()
    start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
