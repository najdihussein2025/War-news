from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.actions.accounts import create_account as create_account_action
from app.actions.accounts import bootstrap_super_admin as bootstrap_super_admin_action
from app.actions.accounts import list_accounts as list_accounts_action
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.dtos import UserCreateDTO, UserResponseDTO
from app.models.accounts import User
from app.services import (
    DuplicateUserError,
    RoleNotFoundError,
    UserPermissionError,
    UserBootstrapError,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.post(
    "/bootstrap",
    response_model=UserResponseDTO,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_super_admin(dto: UserCreateDTO, db: Session = Depends(get_db)) -> UserResponseDTO:
    try:
        return bootstrap_super_admin_action(db, dto)
    except UserBootstrapError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("", response_model=UserResponseDTO, status_code=status.HTTP_201_CREATED)
def create_account(
    dto: UserCreateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponseDTO:
    try:
        return create_account_action(db, dto, current_user)
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[UserResponseDTO])
def list_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[UserResponseDTO]:
    try:
        return list_accounts_action(db, current_user, offset=offset, limit=limit)
    except UserPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
