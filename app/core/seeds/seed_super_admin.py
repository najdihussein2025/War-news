import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.accounts.models import Role, RoleName, User
from app.accounts.services.auth_service import password_context

DEFAULT_SUPER_ADMIN_USERNAME = "superadmin"
DEFAULT_SUPER_ADMIN_FULL_NAME = "Super Admin"


def _ensure_roles(db: Session) -> dict[RoleName, Role]:
    roles = {
        role.name: role
        for role in db.scalars(select(Role).where(Role.name.in_(list(RoleName)))).all()
    }

    for role_name in RoleName:
        if role_name in roles:
            continue

        role = Role(name=role_name)
        db.add(role)
        db.flush()
        roles[role_name] = role

    return roles


def seed_super_admin(db: Session) -> tuple[User, bool]:
    roles = _ensure_roles(db)
    super_admin_role = roles[RoleName.super_admin]
    username = os.getenv("SUPER_ADMIN_SEED_USERNAME", DEFAULT_SUPER_ADMIN_USERNAME)
    full_name = os.getenv("SUPER_ADMIN_SEED_FULL_NAME", DEFAULT_SUPER_ADMIN_FULL_NAME)

    user = db.scalar(select(User).where(User.username == username))
    inserted = user is None

    if user is None:
        user = User(username=username)
        db.add(user)

    user.password_hash = password_context.hash(settings.super_admin_seed_password)
    user.full_name = full_name
    user.role_id = super_admin_role.id
    user.is_active = True
    user.created_by_id = None

    db.commit()
    db.refresh(user)
    return user, inserted


def main() -> None:
    db = SessionLocal()
    try:
        user, inserted = seed_super_admin(db)
        action = "inserted" if inserted else "updated"
        print(
            f"{action}: username={user.username}, "
            f"role={RoleName.super_admin.value}, "
            f"is_active={user.is_active}, "
            "password_source=SUPER_ADMIN_SEED_PASSWORD"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
