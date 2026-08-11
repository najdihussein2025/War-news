from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.dtos import UserCreateDTO, UserResponseDTO
from app.models.accounts import RoleName, User
from app.services import (
    DuplicateUserError,
    RoleNotFoundError,
    UserPermissionError,
    UserService,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.post("", response_model=UserResponseDTO, status_code=status.HTTP_201_CREATED)
def create_account(
    dto: UserCreateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponseDTO:
    service = UserService(db)
    try:
        return service.create_user(dto, current_user)
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
    if current_user.role.name != RoleName.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin users can list accounts.",
        )
    return UserService(db).list_users(offset=offset, limit=limit)
