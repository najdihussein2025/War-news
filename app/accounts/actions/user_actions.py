from sqlalchemy.orm import Session
from uuid import UUID

from app.accounts.dtos import (
    PasswordChangeDTO,
    UserCreateDTO,
    UserResponseDTO,
    UserUpdateDTO,
)
from app.accounts.models import User
from app.accounts.repositories import RoleRepository, UserRepository
from app.accounts.services import UserService


def _service(db: Session) -> UserService:
    return UserService(
        roles=RoleRepository(db),
        users=UserRepository(db),
    )


def create_account(
    db: Session,
    dto: UserCreateDTO,
    current_user: User,
) -> UserResponseDTO:
    user = _service(db).create_user(dto, created_by_user=current_user)
    return UserResponseDTO.model_validate(user)


def bootstrap_super_admin(db: Session, dto: UserCreateDTO) -> UserResponseDTO:
    user = _service(db).bootstrap_super_admin(dto)
    return UserResponseDTO.model_validate(user)


def list_accounts(
    db: Session,
    current_user: User,
    offset: int = 0,
    limit: int = 50,
) -> list[UserResponseDTO]:
    users = _service(db).list_users(
        requested_by_user=current_user,
        offset=offset,
        limit=limit,
    )
    return [UserResponseDTO.model_validate(user) for user in users]


def delete_account(db: Session, user_id: UUID, current_user: User) -> None:
    _service(db).delete_user(user_id, requested_by_user=current_user)


def set_account_active(db: Session, user_id: UUID, is_active: bool, current_user: User) -> UserResponseDTO:
    user = _service(db).set_user_active(user_id, is_active, requested_by_user=current_user)
    return UserResponseDTO.model_validate(user)


def update_account(db: Session, user_id: UUID, dto: UserUpdateDTO, current_user: User) -> UserResponseDTO:
    return UserResponseDTO.model_validate(_service(db).update_user(user_id, dto, current_user))


def change_account_password(
    db: Session,
    user_id: UUID,
    dto: PasswordChangeDTO,
    current_user: User,
) -> None:
    _service(db).change_password(user_id, dto.current_password, dto.new_password, current_user)
