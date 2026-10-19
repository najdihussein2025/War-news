"""Reclassify Arabic drone reports incorrectly stored as helicopters.

Revision ID: 20261019_0081
Revises: 20261019_0080
"""

from alembic import op


revision = "20261019_0081"
down_revision = "20261019_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE air_violations AS av
        SET condition_id = 36,
            version = av.version + 1
        WHERE av.condition_id = 38
          AND (
              av.khabar LIKE '%مسير%'
              OR av.khabar LIKE '%مسيّر%'
              OR av.khabar LIKE '%محلقة%'
              OR COALESCE(
                  (SELECT rm.raw_text FROM raw_messages AS rm WHERE rm.id = av.raw_message_id),
                  ''
              ) LIKE '%مسير%'
              OR COALESCE(
                  (SELECT rm.raw_text FROM raw_messages AS rm WHERE rm.id = av.raw_message_id),
                  ''
              ) LIKE '%مسيّر%'
              OR COALESCE(
                  (SELECT rm.raw_text FROM raw_messages AS rm WHERE rm.id = av.raw_message_id),
                  ''
              ) LIKE '%محلقة%'
          )
          AND av.khabar NOT LIKE '%مروحي%'
          AND av.khabar NOT LIKE '%هليكوبتر%'
        """
    )


def downgrade() -> None:
    # The previous labels were incorrect and cannot be restored safely.
    pass
