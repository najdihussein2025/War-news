"""seed super admin account

Revision ID: 20260811_0011
Revises: 20260811_0010
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260811_0011"
down_revision: Union[str, Sequence[str], None] = "20260811_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUPER_ADMIN_PASSWORD_HASH = (
    "$2b$12$6dy95letwWFOV6PvF4OLtOkhiZMucAjroaNyZRFu/v.1x6VfQpuA."
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO roles (name)
        VALUES ('super_admin'::role_name), ('admin'::role_name)
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO users (
            username,
            password_hash,
            full_name,
            role_id,
            is_active,
            created_by
        )
        SELECT
            'superadmin',
            '{SUPER_ADMIN_PASSWORD_HASH}',
            'Super Admin',
            roles.id,
            true,
            NULL
        FROM roles
        WHERE roles.name = 'super_admin'::role_name
        ON CONFLICT (username) DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            full_name = EXCLUDED.full_name,
            role_id = EXCLUDED.role_id,
            is_active = true,
            created_by = NULL
        """
    )


def downgrade() -> None:
    pass
