"""The one definition of "this incident reports casualties".

An incident qualifies only when the news states an actual number of deaths or
injuries: a positive total, or a positive male/female/children count. Wording
without a number (``count_missing``) and shared-toll flags never qualify; those
rows are reached through the Verification filter instead.

The Incidents casualties filter, the "Reported casualties" KPI and the
``has_reported_casualties`` flag sent to the UI (list and live stream) all use
this expression so they cannot drift.
"""

from sqlalchemy import func, literal, or_, select

from app.news.models import Incident, IncidentDetail

_DETAIL_COUNT_COLUMNS = (
    IncidentDetail.male_d,
    IncidentDetail.male_i,
    IncidentDetail.female_d,
    IncidentDetail.female_i,
    IncidentDetail.children_d,
    IncidentDetail.children_i,
)


def has_reported_casualties_expression() -> object:
    """SQL boolean: any total, male, female or children death/injury count > 0."""
    demographic_count = (
        select(literal(1))
        .where(
            IncidentDetail.incident_id == Incident.id,
            or_(*(func.coalesce(column, 0) > 0 for column in _DETAIL_COUNT_COLUMNS)),
        )
        .exists()
    )
    return or_(
        func.coalesce(Incident.total_deaths, 0) > 0,
        func.coalesce(Incident.total_injuries, 0) > 0,
        demographic_count,
    )
