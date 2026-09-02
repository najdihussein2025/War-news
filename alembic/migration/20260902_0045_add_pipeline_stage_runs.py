"""Add persisted pipeline stage-run telemetry.

Revision ID: 20260902_0045
Revises: 20260902_0044
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260902_0045"
down_revision: Union[str, Sequence[str], None] = "20260902_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_stage_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("sweep_type", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rows_claimed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("aborted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_stage_runs_stage_name", "pipeline_stage_runs", ["stage_name"])
    op.create_index("ix_pipeline_stage_runs_sweep_type", "pipeline_stage_runs", ["sweep_type"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_stage_runs_sweep_type", table_name="pipeline_stage_runs")
    op.drop_index("ix_pipeline_stage_runs_stage_name", table_name="pipeline_stage_runs")
    op.drop_table("pipeline_stage_runs")
