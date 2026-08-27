from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.accounts.actions import create_account as create_account_action
from app.accounts.actions import bootstrap_super_admin as bootstrap_super_admin_action
from app.accounts.actions import change_account_password as change_account_password_action
from app.accounts.actions import list_accounts as list_accounts_action
from app.accounts.actions import delete_account as delete_account_action
from app.accounts.actions import set_account_active as set_account_active_action
from app.accounts.actions import update_account as update_account_action
from app.accounts.actions import acquire_account_edit_lock, release_account_edit_lock
from app.api.deps import get_current_user, require_super_admin
from app.core.database import get_db
from app.accounts.dtos import (
    PasswordChangeDTO,
    UserActiveUpdateDTO,
    UserCreateDTO,
    UserResponseDTO,
    UserUpdateDTO,
)
from app.accounts.models import User
from app.logs.repositories import AuditLogRepository
from app.accounts.services import (
    DuplicateUserError,
    PasswordChangeError,
    RoleNotFoundError,
    UserPermissionError,
    UserBootstrapError,
    UserConflictError,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None

def _user_values(user: User) -> dict:
    return {"username": str(user.username), "full_name": user.full_name, "role_id": user.role_id, "is_active": user.is_active}

def _audit(db: Session, request: Request, actor: User, action: str, target_id: UUID, old: dict | None, new: dict | None) -> None:
    AuditLogRepository(db).record(action=action, target_type="account", target_id=str(target_id), actor_id=actor.id, actor_name=actor.full_name, client_ip=_ip(request), old_values=old, new_values=new)


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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        result = create_account_action(db, dto, current_user)
        _audit(db, request, current_user, "user.created", result.id, None, result.model_dump(mode="json"))
        return result
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
    request: Request,
    version: int = Query(ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> None:
    try:
        existing = db.get(User, user_id)
        old = _user_values(existing) if existing else None
        delete_account_action(db, user_id, version, current_user)
        _audit(db, request, current_user, "user.deleted", user_id, old, None)
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{user_id}/active", response_model=UserResponseDTO)
def set_account_active(
    user_id: UUID,
    dto: UserActiveUpdateDTO,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        existing = db.get(User, user_id)
        old = _user_values(existing) if existing else None
        result = set_account_active_action(db, user_id, dto.is_active, dto.version, current_user)
        _audit(db, request, current_user, "user.activated" if dto.is_active else "user.deactivated", user_id, old, result.model_dump(mode="json"))
        return result
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserResponseDTO)
def update_account(
    user_id: UUID,
    dto: UserUpdateDTO,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        existing = db.get(User, user_id)
        old = _user_values(existing) if existing else None
        result = update_account_action(db, user_id, dto, current_user)
        _audit(db, request, current_user, "user.updated", user_id, old, result.model_dump(mode="json"))
        return result
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{user_id}/edit-lock", response_model=UserResponseDTO)
def acquire_edit_lock(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> UserResponseDTO:
    try:
        return acquire_account_edit_lock(db, user_id, current_user)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{user_id}/edit-lock", status_code=status.HTTP_204_NO_CONTENT)
def release_edit_lock(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> None:
    try:
        release_account_edit_lock(db, user_id, current_user)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def change_account_password(
    user_id: UUID,
    dto: PasswordChangeDTO,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        change_account_password_action(db, user_id, dto, current_user)
        _audit(
            db,
            request,
            current_user,
            "password_change" if user_id == current_user.id else "password_reset",
            user_id,
            None,
            None,
        )
    except PasswordChangeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except UserPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
