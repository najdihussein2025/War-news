from fastapi import FastAPI

app = FastAPI(title="Lebanon News Monitor API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
