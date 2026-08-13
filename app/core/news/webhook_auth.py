import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


def verify_cnrs_webhook_secret(
    x_webhook_secret: str | None = Header(default=None),
) -> None:
    if not x_webhook_secret or not secrets.compare_digest(
        x_webhook_secret,
        settings.cnrs_webhook_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret.",
        )
