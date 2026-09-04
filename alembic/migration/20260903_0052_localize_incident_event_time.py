"""Store source-backed incident dates and times in Beirut local time.

Revision ID: 20260903_0052
Revises: 20260903_0051
"""

from alembic import op


revision = "20260903_0052"
down_revision = "20260903_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE incidents AS i
        SET event_date = (rm.message_datetime AT TIME ZONE 'Asia/Beirut')::date,
            event_time = (rm.message_datetime AT TIME ZONE 'Asia/Beirut')::time
        FROM raw_messages AS rm
        WHERE i.raw_message_id = rm.id
          AND rm.message_datetime IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE incidents AS i
        SET event_date = (rm.message_datetime AT TIME ZONE 'UTC')::date,
            event_time = (rm.message_datetime AT TIME ZONE 'UTC')::time
        FROM raw_messages AS rm
        WHERE i.raw_message_id = rm.id
          AND rm.message_datetime IS NOT NULL
        """
    )
