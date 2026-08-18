from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.accounts.actions.auth_actions import login_account
from app.core.database import get_db
from app.accounts.dtos import (
    LoginDTO,
    CookieLoginResponseDTO,
    SessionResponseDTO,
    UserResponseDTO,
)
from app.accounts.models import User
from app.api.deps import get_current_user
from app.accounts.services.auth_service import AccountInactiveError, InvalidCredentialsError, LoginRateLimitError
from app.api.deps import bearer_scheme
from app.accounts.repositories import AuthSessionRepository, LoginThrottleRepository, UserRepository
from app.accounts.services.auth_service import AuthService
from app.logs.repositories import LoginLogRepository
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _record_login_attempt(
    db: Session,
    *,
    username: str,
    client_ip: str,
    success: bool,
    user_id: UUID | None = None,
    failure_reason: str | None = None,
) -> None:
    try:
        LoginLogRepository(db).record(
            username=username,
            client_ip=client_ip,
            success=success,
            user_id=user_id,
            failure_reason=failure_reason,
        )
    except Exception:
        db.rollback()


@router.get("/me", response_model=SessionResponseDTO)
def current_session(current_user: User = Depends(get_current_user)) -> SessionResponseDTO:
    return SessionResponseDTO(
        user=UserResponseDTO.model_validate(current_user),
        role=current_user.role.name,
    )


@router.post("/login", response_model=CookieLoginResponseDTO)
def login(dto: LoginDTO, request: Request, response: Response, db: Session = Depends(get_db)) -> CookieLoginResponseDTO:
    client_ip = request.client.host if request.client else "unknown"
    try:
        result = login_account(db, dto, client_ip, request.state.login_device_id)
        _record_login_attempt(
            db,
            username=dto.username,
            client_ip=client_ip,
            success=True,
            user_id=result.user.id,
        )
        response.set_cookie(
            key="access_token",
            value=result.access_token,
            max_age=60 * 60 * 12,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            path="/",
        )
        return CookieLoginResponseDTO(user=result.user, role=result.role)
    except AccountInactiveError as exc:
        _record_login_attempt(db, username=dto.username, client_ip=client_ip, success=False, failure_reason="inactive")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        _record_login_attempt(db, username=dto.username, client_ip=client_ip, success=False, failure_reason="invalid_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except LoginRateLimitError as exc:
        _record_login_attempt(db, username=dto.username, client_ip=client_ip, success=False, failure_reason="rate_limited")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get("access_token") or (credentials.credentials if credentials else None)
    if token:
        AuthService(UserRepository(db), AuthSessionRepository(db), LoginThrottleRepository(db)).logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key="access_token", path="/", samesite=settings.auth_cookie_samesite)
    return response
