from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.actions.accounts.auth_actions import login_account
from app.core.database import get_db
from app.dtos import LoginDTO, LoginResponseDTO, SessionResponseDTO, UserResponseDTO
from app.models.accounts import User
from app.api.dependencies import get_current_user
from app.services.auth_service import AccountInactiveError, InvalidCredentialsError, LoginRateLimitError
from app.api.dependencies import bearer_scheme
from app.repositories import AuthSessionRepository, LoginThrottleRepository, UserRepository
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=SessionResponseDTO)
def current_session(current_user: User = Depends(get_current_user)) -> SessionResponseDTO:
    return SessionResponseDTO(
        user=UserResponseDTO.model_validate(current_user),
        role=current_user.role.name,
    )


@router.post("/login", response_model=LoginResponseDTO)
def login(dto: LoginDTO, request: Request, db: Session = Depends(get_db)) -> LoginResponseDTO:
    try:
        client_ip = request.client.host if request.client else "unknown"
        return login_account(db, dto, client_ip, request.state.login_device_id)
    except AccountInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except LoginRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)) -> Response:
    if credentials:
        AuthService(UserRepository(db), AuthSessionRepository(db), LoginThrottleRepository(db)).logout(credentials.credentials)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
