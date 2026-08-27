from passlib.context import CryptContext
from app.accounts.dtos import (
    UserCreateDTO,
    UserUpdateDTO,
)
from app.accounts.models import RoleName, User
from app.accounts.repositories import AuthSessionRepository, RoleRepository, UserRepository
from sqlalchemy.orm.exc import StaleDataError

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserPermissionError(Exception):
    pass


class DuplicateUserError(Exception):
    pass


class RoleNotFoundError(Exception):
    pass


class UserBootstrapError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class PasswordChangeError(Exception):
    pass


class UserConflictError(Exception):
    pass


class UserService:
    def __init__(
        self,
        roles: RoleRepository,
        users: UserRepository,
        sessions: AuthSessionRepository,
    ) -> None:
        self.roles = roles
        self.users = users
        self.sessions = sessions

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

    def delete_user(self, user_id, version: int, requested_by_user: User) -> None:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can delete accounts.")
        if requested_by_user.id == user_id:
            raise UserPermissionError("You cannot delete your own active account.")

        user = self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User does not exist.")
        try:
            self.users.delete_by_admin(user.id, version, requested_by_user.id)
        except StaleDataError as exc:
            raise UserConflictError("This account is being edited or was updated by another super administrator.") from exc

    def set_user_active(self, user_id, is_active: bool, version: int, requested_by_user: User) -> User:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can change account status.")
        if requested_by_user.id == user_id and not is_active:
            raise UserPermissionError("You cannot deactivate your own active account.")

        user = self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User does not exist.")
        try:
            updated = self.users.update_by_admin(
                user.id, version, requested_by_user.id, {"is_active": is_active}
            )
        except StaleDataError as exc:
            raise UserConflictError("This account is being edited or was updated by another super administrator.") from exc
        if updated is None:
            raise UserNotFoundError("User does not exist.")
        return updated

    def update_user(self, user_id, dto: UserUpdateDTO, requested_by_user: User) -> User:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can edit accounts.")
        user = self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User does not exist.")
        duplicate = self.users.get_by_username(dto.username)
        if duplicate is not None and duplicate.id != user.id:
            raise DuplicateUserError("Username already exists.")
        role = self.roles.get_by_id(dto.role_id)
        if role is None:
            raise RoleNotFoundError("Role does not exist.")

        values = {
            "username": dto.username,
            "full_name": dto.full_name,
            "role_id": role.id,
        }
        if dto.password:
            values["password_hash"] = password_context.hash(dto.password)
        try:
            updated = self.users.update_by_admin(user.id, dto.version, requested_by_user.id, values)
        except StaleDataError as exc:
            raise UserConflictError("This account is being edited or was updated by another super administrator.") from exc
        if updated is None:
            raise UserNotFoundError("User does not exist.")
        return updated

    def acquire_edit_lock(self, user_id, requested_by_user: User) -> User:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can edit accounts.")
        try:
            user = self.users.acquire_edit_lock(user_id, requested_by_user.id)
        except StaleDataError as exc:
            raise UserConflictError("This account is currently being edited by another super administrator.") from exc
        if user is None:
            raise UserNotFoundError("User does not exist.")
        return user

    def release_edit_lock(self, user_id, requested_by_user: User) -> None:
        if requested_by_user.role.name != RoleName.super_admin:
            raise UserPermissionError("Only super_admin users can edit accounts.")
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError("User does not exist.")
        self.users.release_edit_lock(user_id, requested_by_user.id)

    def change_password(self, user_id, current_password: str, new_password: str, requested_by_user: User) -> User:
        target_user = self.users.get_by_id(user_id)
        if target_user is None:
            raise UserNotFoundError("User does not exist.")

        is_self = requested_by_user.id == user_id
        is_super_admin_override = requested_by_user.role.name == RoleName.super_admin

        if not is_self and not is_super_admin_override:
            raise UserPermissionError("You do not have permission to change this password.")

        if not password_context.verify(current_password, requested_by_user.password_hash):
            raise PasswordChangeError("Current password is incorrect.")

        target_user.password_hash = password_context.hash(new_password)
        updated = self.users.update(target_user)
        self.sessions.revoke_all_for_user(target_user.id)
        return updated
