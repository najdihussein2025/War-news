from fastapi import FastAPI

from app.api.routes.accounts import router as accounts_router

app = FastAPI(title="Lebanon News Monitor API")
app.include_router(accounts_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
