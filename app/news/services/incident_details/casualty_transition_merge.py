from __future__ import annotations

from typing import Any

from app.news.models import Incident

_STATUS_FIELDS = {
    "injured": "injuries",
    "deceased": "deaths",
}

_SUPPORTED_TRANSITION = ("injured", "deceased")


def parse_casualty_transitions(
    raw: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not raw:
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        from_status = item.get("from_status")
        to_status = item.get("to_status")
        count = item.get("count")
        if (
            from_status not in _STATUS_FIELDS
            or to_status not in _STATUS_FIELDS
            or not isinstance(count, int)
            or count <= 0
        ):
            continue
        parsed.append(
            {
                "from_status": from_status,
                "to_status": to_status,
                "count": count,
            }
        )
    return parsed


def apply_casualty_transitions(
    existing: Incident,
    transitions: list[dict[str, Any]] | None,
) -> tuple[frozenset[str], dict[str, Any], bool]:
    """Apply status transitions against stored counts before max-wins merge.

    Returns ``(fields_set_by_transition, provenance, needs_review)``.
    """
    fields_set: set[str] = set()
    provenance: dict[str, Any] = {}
    needs_review = False

    for transition in parse_casualty_transitions(transitions):
        from_status = transition["from_status"]
        to_status = transition["to_status"]
        if (from_status, to_status) != _SUPPORTED_TRANSITION:
            continue

        from_field = _STATUS_FIELDS[from_status]
        to_field = _STATUS_FIELDS[to_status]
        requested = int(transition["count"])
        available = int(getattr(existing, from_field) or 0)
        applied = min(requested, available)
        if applied < requested:
            needs_review = True

        if applied == 0:
            continue

        setattr(existing, from_field, available - applied)
        setattr(existing, to_field, int(getattr(existing, to_field) or 0) + applied)
        fields_set.update({from_field, to_field})
        provenance["deaths_transitioned_from_injuries"] = {
            "count": applied,
            "requested_count": requested,
        }

    return frozenset(fields_set), provenance, needs_review


def sync_transition_totals(
    existing: Incident,
    fields_set_by_transition: frozenset[str],
) -> None:
    if "deaths" in fields_set_by_transition:
        existing.total_deaths = existing.deaths
    if "injuries" in fields_set_by_transition:
        existing.total_injuries = existing.injuries
