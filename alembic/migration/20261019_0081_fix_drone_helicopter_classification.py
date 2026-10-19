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
        CREATE TABLE IF NOT EXISTS air_violation_drone_reclass_backup_20261019 (
            air_violation_id BIGINT PRIMARY KEY,
            condition_id INTEGER NOT NULL,
            version INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO air_violation_drone_reclass_backup_20261019
            (air_violation_id, condition_id, version)
        SELECT av.id, av.condition_id, av.version
        FROM air_violations AS av
        WHERE av.condition_id = 38
          AND (av.khabar LIKE '%مسير%' OR av.khabar LIKE '%مسيّر%' OR av.khabar LIKE '%محلقة%'
               OR COALESCE((SELECT rm.raw_text FROM raw_messages rm WHERE rm.id=av.raw_message_id), '') LIKE '%مسير%'
               OR COALESCE((SELECT rm.raw_text FROM raw_messages rm WHERE rm.id=av.raw_message_id), '') LIKE '%مسيّر%'
               OR COALESCE((SELECT rm.raw_text FROM raw_messages rm WHERE rm.id=av.raw_message_id), '') LIKE '%محلقة%')
          AND av.khabar NOT LIKE '%مروحي%' AND av.khabar NOT LIKE '%هليكوبتر%'
        ON CONFLICT (air_violation_id) DO NOTHING
        """
    )
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
    op.execute(
        """
        UPDATE air_violations av
        SET condition_id=b.condition_id, version=b.version
        FROM air_violation_drone_reclass_backup_20261019 b
        WHERE av.id=b.air_violation_id
        """
    )
    op.execute("DROP TABLE air_violation_drone_reclass_backup_20261019")
