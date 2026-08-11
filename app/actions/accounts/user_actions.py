from sqlalchemy.orm import Session

from app.dtos import UserCreateDTO, UserResponseDTO
from app.models.accounts import User
from app.repositories import RoleRepository, UserRepository
from app.services import UserService


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
