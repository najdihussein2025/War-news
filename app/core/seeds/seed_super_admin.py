from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.accounts import Role, RoleName, User
from app.services.auth_service import password_context

SUPER_ADMIN_USERNAME = "superadmin"
SUPER_ADMIN_PASSWORD = "password"
SUPER_ADMIN_FULL_NAME = "Super Admin"


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

    user = db.scalar(select(User).where(User.username == SUPER_ADMIN_USERNAME))
    inserted = user is None

    if user is None:
        user = User(username=SUPER_ADMIN_USERNAME)
        db.add(user)

    user.password_hash = password_context.hash(SUPER_ADMIN_PASSWORD)
    user.full_name = SUPER_ADMIN_FULL_NAME
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
            f"is_active={user.is_active}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
