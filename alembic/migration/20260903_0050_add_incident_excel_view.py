"""Add a read-only incident view shaped like the legacy Excel workbook.

Revision ID: 20260903_0050
Revises: 20260903_0049
"""

from alembic import op

from app.news.services.incident_workbook_service import (
    INCIDENT_DETAIL_FIELD_MAP,
    INCIDENT_FIELD_MAP,
    INCIDENT_INT_FIELD_MAP,
    LOOKUP_ONLY_HEADERS,
)


revision = "20260903_0050"
down_revision = "20260903_0049"
branch_labels = None
depends_on = None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _view_sql() -> str:
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
        **{
            header: f"d.{field}"
            for header, field in INCIDENT_DETAIL_FIELD_MAP.items()
        },
    }
    # Preserve the physical order of Fields sample.xlsx as well as its names.
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
CREATE VIEW incident_excel_view AS
SELECT
    {select_columns}
FROM incidents AS i
LEFT JOIN villages AS v ON v.id = i.village_id
LEFT JOIN conditions AS c ON c.id = i.condition_id
LEFT JOIN sources AS s ON s.id = i.source_id
LEFT JOIN incident_details AS d ON d.incident_id = i.id
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS incident_excel_view")
    op.execute(_view_sql())


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS incident_excel_view")
