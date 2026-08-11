from fastapi import HTTPException, status

from app.models.accounts import User


def get_current_user() -> User:
    # TODO: Replace with real authentication once the auth layer is built.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication is not implemented yet.",
    )
