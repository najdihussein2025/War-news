from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.actions.accounts import create_account as create_account_action
from app.actions.accounts import bootstrap_super_admin as bootstrap_super_admin_action
from app.actions.accounts import list_accounts as list_accounts_action
from app.actions.accounts import delete_account as delete_account_action
from app.actions.accounts import set_account_active as set_account_active_action
from app.actions.accounts import update_account as update_account_action
from app.api.dependencies import require_super_admin
from app.core.database import get_db
from app.dtos import UserActiveUpdateDTO, UserCreateDTO, UserResponseDTO, UserUpdateDTO
from app.models.accounts import User
from app.services import (
    DuplicateUserError,
    RoleNotFoundError,
    UserPermissionError,
    UserBootstrapError,
    UserNotFoundError,
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
    current_user: User = Depends(require_super_admin),
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
    current_user: User = Depends(require_super_admin),
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


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> None:
    try:
        delete_account_action(db, user_id, current_user)
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{user_id}/active", response_model=UserResponseDTO)
def set_account_active(
    user_id: UUID,
    dto: UserActiveUpdateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        return set_account_active_action(db, user_id, dto.is_active, current_user)
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserResponseDTO)
def update_account(
    user_id: UUID,
    dto: UserUpdateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        return update_account_action(db, user_id, dto, current_user)
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
