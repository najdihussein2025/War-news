from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.accounts import User
from app.repositories import UserRepository


def get_current_user(db: Session = Depends(get_db)) -> User:
    # TODO: Resolve the authenticated bearer token once the auth layer is built.
    # The superadmin preview currently acts as the first active superadmin.
    user = UserRepository(db).get_active_super_admin()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create the first super_admin account before managing users.",
        )
    return user
