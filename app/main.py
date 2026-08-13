import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.accounts import router as accounts_router
from app.api.routes.auth import router as auth_router
from app.api.news.webhook_router import router as webhook_router
from app.api.news.sources_router import router as sources_router
from app.core.scheduler import start_scheduler, stop_scheduler

app = FastAPI(title="Lebanon News Monitor API")


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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(accounts_router)
app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(sources_router)


@app.on_event("startup")
def startup() -> None:
    start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
