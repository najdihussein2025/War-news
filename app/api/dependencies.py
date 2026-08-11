from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.accounts import RoleName, User
from app.repositories import AuthSessionRepository
from app.services.auth_service import hash_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    session = AuthSessionRepository(db).get_active(hash_access_token(credentials.credentials)) if credentials else None
    user = session.user if session else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: RoleName) -> Callable[..., User]:
    def role_dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.name not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return current_user

    return role_dependency


require_admin = require_roles(RoleName.admin, RoleName.super_admin)
require_super_admin = require_roles(RoleName.super_admin)
