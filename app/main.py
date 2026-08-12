from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.accounts import router as accounts_router
from app.api.routes.auth import router as auth_router
from app.core.scheduler import start_scheduler, stop_scheduler

app = FastAPI(title="Lebanon News Monitor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(accounts_router)
app.include_router(auth_router)


@app.on_event("startup")
def startup() -> None:
    start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
