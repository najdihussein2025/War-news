"""add anonymous car casualty fields for genderless vehicle tolls

Revision ID: 20260923_0063
Revises: 20260923_0062
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.news.services.incidents.incident_workbook_service import (
    INCIDENT_DETAIL_FIELD_MAP,
    INCIDENT_FIELD_MAP,
    INCIDENT_INT_FIELD_MAP,
    LOOKUP_ONLY_HEADERS,
)


revision: str = "20260923_0063"
down_revision: Union[str, Sequence[str], None] = "20260923_0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _view_sql(*, include_anonymous_car: bool) -> str:
    lookup_expressions = {
        "Column_1": "COALESCE(v.ref_name_en, v.cad_name, v.acs_name)",
        "Column_2": "COALESCE(v.acs_name, v.cad_name, v.ref_name_en)",
        "ACS_Code": "v.acs_code",
        "ACS_Name": "v.acs_name",
        "C_Ref_Eng": "v.ref_name_en",
        "C_Ref_Arab": "v.ref_name_ar",
        "Gove_E": "v.mohafaza_en",
        "Gove_A": "v.mohafaza_ar",
        "Dist_E": "v.caza_en",
        "Dist_A": "v.caza_ar",
        "Action_E": "c.action_en",
        "Action_A": "c.action_ar",
        "Source": "s.name",
    }
    expressions = {
        **lookup_expressions,
        **{header: f"i.{field}" for header, field in INCIDENT_FIELD_MAP.items()},
        **{header: f"i.{field}" for header, field in INCIDENT_INT_FIELD_MAP.items()},
        "Time": "i.event_time",
        "Date": "i.event_date",
        **{header: f"d.{field}" for header, field in INCIDENT_DETAIL_FIELD_MAP.items()},
    }
    if not include_anonymous_car:
        expressions["Anonymous_CD"] = "NULL::integer"
        expressions["Anonymous_CI"] = "NULL::integer"
    headers = (
        ["Column_1", "Column_2"]
        + list(LOOKUP_ONLY_HEADERS[1:9])
        + ["Month", "Action_E", "Action_A", "Khabar", "Source", "Time", "Date"]
        + ["Total_D", "Total_Inj", "Death", "Injuries"]
        + list(INCIDENT_DETAIL_FIELD_MAP)
        + ["NOTE", "MOH", "Worker Name", "Links"]
    )
    select_columns = ",\n    ".join(
        f"{expressions[header]} AS {_quote(header)}" for header in headers
    )
    return f"""
CREATE OR REPLACE VIEW incident_excel_view AS
SELECT
    {select_columns}
FROM incidents AS i
LEFT JOIN villages AS v ON v.id = i.village_id
LEFT JOIN conditions AS c ON c.id = i.condition_id
LEFT JOIN sources AS s ON s.id = i.source_id
LEFT JOIN incident_details AS d ON d.incident_id = i.id
"""


def upgrade() -> None:
    op.add_column(
        "incident_details",
        sa.Column("cara_d", sa.Integer(), nullable=True),
    )
    op.add_column(
        "incident_details",
        sa.Column("cara_i", sa.Integer(), nullable=True),
    )
    # Existing rows that already stored genderless car tolls on card/cari
    # with no demographic splits: copy into the anonymous buckets.
    op.execute(
        """
        UPDATE incident_details
        SET cara_d = card
        WHERE card IS NOT NULL
          AND card > 0
          AND cara_d IS NULL
          AND COALESCE(carm_d, 0) = 0
          AND COALESCE(carf_d, 0) = 0
          AND COALESCE(carc_d, 0) = 0
        """
    )
    op.execute(
        """
        UPDATE incident_details
        SET cara_i = cari
        WHERE cari IS NOT NULL
          AND cari > 0
          AND cara_i IS NULL
          AND COALESCE(carm_i, 0) = 0
          AND COALESCE(carf_i, 0) = 0
          AND COALESCE(carc_i, 0) = 0
        """
    )
    op.execute(_view_sql(include_anonymous_car=True))


def downgrade() -> None:
    op.execute(_view_sql(include_anonymous_car=False))
    op.drop_column("incident_details", "cara_i")
    op.drop_column("incident_details", "cara_d")
