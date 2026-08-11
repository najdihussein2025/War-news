from passlib.context import CryptContext
from app.dtos import UserCreateDTO
from app.models.accounts import RoleName, User
from app.repositories import RoleRepository, UserRepository

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserPermissionError(Exception):
    pass


class DuplicateUserError(Exception):
    pass


class RoleNotFoundError(Exception):
    pass


class UserBootstrapError(Exception):
    pass


class UserService:
    def __init__(self, roles: RoleRepository, users: UserRepository) -> None:
        self.roles = roles
        self.users = users

    def create_user(
        self,
        dto: UserCreateDTO,
        created_by_user: User,
    ) -> User:
        if created_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can create accounts.")

        if self.users.get_by_username(dto.username) is not None:
            raise DuplicateUserError("Username already exists.")

        role = self.roles.get_by_id(dto.role_id)
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
        return created_user

    def bootstrap_super_admin(self, dto: UserCreateDTO) -> User:
        if self.users.exists():
            raise UserBootstrapError("The first user has already been created.")

        role = self.roles.get_by_id(dto.role_id)
        if role is None:
            raise RoleNotFoundError("Role does not exist.")
        if role.name != RoleName.super_admin:
            raise UserBootstrapError("The first user must be a super_admin.")
        if self.users.get_by_username(dto.username) is not None:
            raise DuplicateUserError("Username already exists.")

        return self.users.create(
            User(
                username=dto.username,
                password_hash=password_context.hash(dto.password),
                full_name=dto.full_name,
                role_id=role.id,
                created_by_id=None,
            )
        )

    def list_users(
        self,
        requested_by_user: User,
        offset: int = 0,
        limit: int = 50,
    ) -> list[User]:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can list accounts.")

        return self.users.list_all(offset, limit)
