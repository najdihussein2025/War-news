from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.dtos import UserCreateDTO, UserResponseDTO
from app.models.accounts import Role, RoleName, User
from app.repositories import RoleRepository, UserRepository

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserPermissionError(Exception):
    pass


class DuplicateUserError(Exception):
    pass


class RoleNotFoundError(Exception):
    pass


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.roles = RoleRepository(db)
        self.users = UserRepository(db)

    def create_user(
        self,
        dto: UserCreateDTO,
        created_by_user: User,
    ) -> UserResponseDTO:
        if created_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can create accounts.")

        if self.users.get_by_username(dto.username) is not None:
            raise DuplicateUserError("Username already exists.")

        role = self.db.get(Role, dto.role_id)
        if role is None:
            raise RoleNotFoundError("Role does not exist.")

        user = User(
            username=dto.username,
            password_hash=password_context.hash(dto.password),
            full_name=dto.full_name,
            role_id=dto.role_id,
            created_by_id=created_by_user.id,
        )
        created_user = self.users.create(user)

        # TODO: Write audit_logs account creation entry once audit_logs exists.
        self.db.commit()
        self.db.refresh(created_user)
        return UserResponseDTO.model_validate(created_user)

    def list_users(self, offset: int = 0, limit: int = 50) -> list[UserResponseDTO]:
        return [UserResponseDTO.model_validate(user) for user in self.users.list_all(offset, limit)]
