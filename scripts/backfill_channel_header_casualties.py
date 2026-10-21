"""Clean casualty values that only a channel/page header «proved».

``صفحة الإعلامي الشهيد علي شعيب`` heads many posts; its «الشهيد» was read as a death
and copied onto incidents (raw 44770 -> 44767, 37903 -> 37888 ...). For every live
incident (``is_deleted = false``) this re-checks the stored casualty values against
the header-stripped BODY of the canonical message and of every linked/merged message
(``connected_casualty_sources``), using the stored text only — no LLM calls unless
``--reextract`` is passed.

* A death/injury grounded in the body of at least one linked message is KEPT.
* Values whose only source is a header token, or that no body supports and whose body has
  no casualty wording (or only a vague one), are set to NULL,
  while an unproven value whose body still has casualty wording is KEPT and listed as
  ``needs_review`` for a human, together with the matching ``incident_details`` gender/children fields.
* ``casualty_status`` is re-aligned with the numbers, rows of a shared-toll group are
  all flagged Needs verification, and an Unclassified action is flagged too.
* Rows an admin edited or verified are NEVER touched; they are listed in the report.

Dry-run is the default: nothing is written unless ``--apply`` is passed, and the
reviewed CSV should be read first. Run it inside the backend container:

    docker compose exec backend python -m scripts.backfill_channel_header_casualties
"""
from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.news.services  # noqa: F401  (import order: loader <-> matching_service)

from app.core.llm_knowledge.message_text import clean_message_text
from app.core.llm_knowledge.source_headers import header_spans
from app.news.models import Incident, IncidentDetail, UpdateAction
from app.news.models.bulletin_casualty_group import (
    BulletinCasualtyGroup,
    BulletinCasualtyGroupMember,
    CasualtyScope,
)
from app.news.services.incident_details.casualty_merge_provenance import vet_incoming_casualties
from app.news.services.incident_details.casualty_status import enforce_status_matches_numbers
from app.core.text_normalization import normalize_arabic_text
from app.news.services.incident_details.casualty_text import (
    bare_token_lacks_event_context,
    has_casualty_wording,
    has_vague_quantifier,
    strip_page_header,
)
from app.news.services.incident_details.incident_casualty_recompute import (
    ConnectedCasualtySource,
    _admin_edited,
    connected_casualty_sources,
)
from app.news.services.incidents.incident_change_log import record_incident_change
from app.news.services.materialization.verification_signals import (
    SHARED_TOLL_DISTRIBUTE_REASON,
    UNCLASSIFIED_REVIEW_REASON,
    is_unclassified_condition,
)

logger = logging.getLogger(__name__)

OUT_CSV = Path(__file__).resolve().parent / "out" / "backfill_channel_header_casualties.csv"

# incident column / detail column -> vet key; a "kind" is every field of deaths or injuries.
KIND_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    # (location, attribute, vet key)
    "deaths": (
        ("incident", "deaths", "deaths"),
        ("incident", "total_deaths", "total_deaths"),
        ("detail", "male_d", "male_d"),
        ("detail", "female_d", "female_d"),
        ("detail", "children_d", "children_d"),
    ),
    "injuries": (
        ("incident", "injuries", "injuries"),
        ("incident", "total_injuries", "total_injuries"),
        ("detail", "male_i", "male_i"),
        ("detail", "female_i", "female_i"),
        ("detail", "children_i", "children_i"),
    ),
}
STATUS_ATTRS = (
    "casualty_status",
    "casualty_deaths_status",
    "casualty_injuries_status",
    "casualty_status_evidence",
)


@dataclass
class Change:
    field: str
    old: Any
    new: Any
    reason: str


@dataclass
class IncidentPlan:
    incident_id: Any
    village: str
    event_date: str
    raw_ids: list[int]
    skipped: str | None = None
    kept: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    # Ungrounded values whose body still has casualty wording: kept, listed for a human.
    review: list[Change] = field(default_factory=list)

    @property
    def cleared(self) -> list[Change]:
        return [c for c in self.changes if c.reason in ("header_only", "no_body_grounding", "vague_quantifier")]

    @property
    def status_fixed(self) -> list[Change]:
        return [c for c in self.changes if c.reason == "status_matches_numbers"]

    @property
    def flagged(self) -> list[Change]:
        return [c for c in self.changes if c.reason in ("shared_toll", "unclassified_action")]


def _is_positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _body(text: str | None) -> str:
    return strip_page_header(clean_message_text(text or ""))


_EVIDENCE_FIELD_TO_KEY = {
    "deaths": "deaths", "injuries": "injuries",
    "total_deaths": "total_deaths", "total_injuries": "total_injuries",
    "male_deaths": "male_d", "male_injuries": "male_i",
    "female_deaths": "female_d", "female_injuries": "female_i",
    "children_deaths": "children_d", "children_injuries": "children_i",
}


def _stored_evidence_keys(source: ConnectedCasualtySource) -> set[str]:
    """Keys whose stored extraction evidence span sits in the header-stripped body.

    Covers real casualties the mention parser cannot count by itself («استشهد الشاب
    فلان …»). A span inside the header, or a bare «شهيد» without event context, never counts.
    """
    extraction = source.extraction_result or {}
    casualties = extraction.get("casualties") or {}
    body = _body(source.text)
    normalized_body = normalize_arabic_text(body)
    keys: set[str] = set()
    for item in extraction.get("casualty_evidence") or []:
        if not isinstance(item, dict):
            continue
        field_name, span = item.get("field"), item.get("evidence_span")
        key = _EVIDENCE_FIELD_TO_KEY.get(field_name)
        if key is None or not span or not _is_positive(casualties.get(field_name)):
            continue
        if normalize_arabic_text(clean_message_text(span)) not in normalized_body:
            continue
        if header_spans(span) or bare_token_lacks_event_context(body, span):
            continue
        keys.add(key)
    return keys


def grounded_keys(sources: list[ConnectedCasualtySource], values: dict[str, int]) -> set[str]:
    """Vet keys of ``values`` that the header-stripped body of at least one source proves."""
    grounded: set[str] = set()
    for source in sources:
        grounded |= _stored_evidence_keys(source) & set(values)
        stand_in = SimpleNamespace(id=source.raw_message_id, raw_text=source.text, match_result=None)
        # No village check: the backfill is conservative and must never drop a real casualty.
        decision = vet_incoming_casualties(stand_in, dict(values), incident_village_id=None)
        grounded |= {key for key in values if decision.values.get(key) is not None}
    # A count and its roll-up are one claim.
    for base, total in (("deaths", "total_deaths"), ("injuries", "total_injuries")):
        if base in grounded or total in grounded:
            grounded |= {base, total} & set(values)
    return grounded


def _body_wording(sources: list[ConnectedCasualtySource], kind: str) -> str:
    """"wording" (real casualty words), "vague" (only «عشرات»/«وقوع إصابات») or "none"."""
    wording = vague = False
    for source in sources:
        body = _body(source.text)
        if has_vague_quantifier(body, kind):
            vague = True
        elif has_casualty_wording(body, kind):
            wording = True
    return "wording" if wording else "vague" if vague else "none"


def _header_only(sources: list[ConnectedCasualtySource]) -> bool:
    """True when a linked message carries a registered channel/page header."""
    return any(header_spans(source.text) for source in sources)


def plan_incident(
    db: Session,
    incident: Incident,
    detail: IncidentDetail | None,
    *,
    reextract_supports=None,
    shared_toll_group: BulletinCasualtyGroup | None = None,
) -> IncidentPlan:
    sources = connected_casualty_sources(db, incident)
    plan = IncidentPlan(
        incident_id=incident.id,
        village=incident.village_display_name or str(incident.village_id),
        event_date=incident.event_date.isoformat() if incident.event_date else "",
        raw_ids=[source.raw_message_id for source in sources],
    )
    if incident.verified_by_user_id is not None:
        plan.skipped = "verified"
        return plan
    if _admin_edited(db, incident):
        plan.skipped = "admin_edited"
        return plan

    def current(location: str, attr: str) -> Any:
        holder = incident if location == "incident" else detail
        return getattr(holder, attr, None) if holder is not None else None

    shadow = SimpleNamespace(
        **{attr: getattr(incident, attr, None) for attr in ("deaths", "injuries", "total_deaths", "total_injuries")},
        **{attr: getattr(incident, attr, None) for attr in STATUS_ATTRS},
    )
    for kind, fields in KIND_FIELDS.items():
        positives = {key: current(loc, attr) for loc, attr, key in fields if _is_positive(current(loc, attr))}
        if not positives:
            continue
        grounded = grounded_keys(sources, positives)
        if not grounded and reextract_supports is not None and reextract_supports(sources, kind):
            grounded = set(positives)
        reason = "no_body_grounding"
        if not grounded:
            body_state = _body_wording(sources, kind)
            if body_state == "wording":
                # Never remove what may be a real casualty: report it for a human instead.
                for loc, attr, key in fields:
                    value = current(loc, attr)
                    if _is_positive(value):
                        label = attr if loc == "incident" else f"detail.{attr}"
                        plan.review.append(Change(label, value, value, "needs_review"))
                continue
            if _header_only(sources):
                reason = "header_only"
            elif body_state == "vague":
                reason = "vague_quantifier"
        main_grounded = bool(grounded & {"deaths", "total_deaths", "injuries", "total_injuries"})
        for loc, attr, key in fields:
            value = current(loc, attr)
            if not _is_positive(value):
                continue
            if loc == "detail" and main_grounded:
                # Gender/children breakdowns go only together with their main count: the
                # backfill removes header contamination, it does not re-judge demographics.
                plan.kept.append(f"detail.{attr}={value}")
                continue
            if key in grounded:
                plan.kept.append(f"{attr}={value}")
                continue
            label = attr if loc == "incident" else f"detail.{attr}"
            plan.changes.append(Change(label, value, None, reason))
            if loc == "incident":
                setattr(shadow, attr, None)
    enforce_status_matches_numbers(shadow)
    # Real casualties kept for review, or kept only in the gender/children breakdown, are
    # not "no numbers": never downgrade such a row to none_mentioned or drop its evidence.
    protected = bool(plan.review) or any(item.startswith("detail.") for item in plan.kept)
    for attr in STATUS_ATTRS:
        new_value = getattr(shadow, attr)
        if protected and new_value in (None, "none_mentioned") and getattr(incident, attr, None) not in (None, "none_mentioned"):
            continue
        if getattr(shadow, attr) != getattr(incident, attr, None):
            plan.changes.append(
                Change(attr, getattr(incident, attr, None), getattr(shadow, attr), "status_matches_numbers")
            )
    # Review flags (verified rows were skipped above; a rejected row stays rejected).
    if incident.verification_status != "rejected":
        reasons = [incident.verification_reason] if incident.verification_reason else []
        flagged_by: list[str] = []
        if shared_toll_group is not None and not (
            incident.verification_status == "needs_verification"
            and incident.verification_reason == SHARED_TOLL_DISTRIBUTE_REASON
        ):
            reasons = [SHARED_TOLL_DISTRIBUTE_REASON]
            flagged_by.append("shared_toll")
        if is_unclassified_condition(db, incident.condition_id) and UNCLASSIFIED_REVIEW_REASON not in "; ".join(reasons):
            reasons.append(UNCLASSIFIED_REVIEW_REASON)
            flagged_by.append("unclassified_action")
        if flagged_by:
            plan.changes.append(
                Change("verification_reason", incident.verification_reason, "; ".join(reasons), flagged_by[0])
            )
    return plan


def _shared_toll_groups(db: Session) -> dict[Any, BulletinCasualtyGroup]:
    rows = db.execute(
        select(BulletinCasualtyGroupMember.incident_id, BulletinCasualtyGroup)
        .join(BulletinCasualtyGroup, BulletinCasualtyGroup.id == BulletinCasualtyGroupMember.group_id)
        .where(
            BulletinCasualtyGroupMember.incident_id.is_not(None),
            BulletinCasualtyGroup.casualty_scope == CasualtyScope.bulletin_aggregate,
        )
    ).all()
    return {incident_id: group for incident_id, group in rows}


def collect_plans(db: Session, *, reextract_supports=None) -> list[IncidentPlan]:
    groups = _shared_toll_groups(db)
    plans: list[IncidentPlan] = []
    incidents = db.scalars(select(Incident).where(Incident.is_deleted.is_(False)).order_by(Incident.created_at)).all()
    for incident in incidents:
        detail = db.get(IncidentDetail, incident.id)
        plans.append(
            plan_incident(
                db, incident, detail,
                reextract_supports=reextract_supports,
                shared_toll_group=groups.get(incident.id),
            )
        )
    return plans


def write_csv(plans: list[IncidentPlan], path: Path = OUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["incident_id", "village", "date", "field", "old -> new", "reason", "linked_raw_ids"])
        for plan in plans:
            linked = " ".join(str(i) for i in plan.raw_ids)
            if plan.skipped:
                writer.writerow([plan.incident_id, plan.village, plan.event_date, "(row skipped)", "", plan.skipped, linked])
                continue
            for change in [*plan.changes, *plan.review]:
                writer.writerow([
                    plan.incident_id, plan.village, plan.event_date, change.field,
                    f"{change.old} -> {change.new}", change.reason, linked,
                ])
    return path


def summarize(plans: list[IncidentPlan]) -> Counter:
    counts: Counter = Counter()
    for plan in plans:
        if plan.skipped:
            counts[f"skipped_{plan.skipped}"] += 1
            continue
        counts["kept"] += len(plan.kept)
        counts["cleared"] += len(plan.cleared)
        counts["status_fixed"] += 1 if plan.status_fixed else 0
        counts["newly_flagged"] += 1 if plan.flagged else 0
        counts["needs_review"] += len(plan.review)
    return counts


def apply_plan(db: Session, plan: IncidentPlan) -> None:
    incident = db.get(Incident, plan.incident_id)
    if incident is None:
        raise LookupError(f"incident {plan.incident_id} disappeared")
    detail = db.get(IncidentDetail, plan.incident_id)
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for change in plan.changes:
        old[change.field], new[change.field] = change.old, change.new
        if change.field.startswith("detail."):
            if detail is not None:
                setattr(detail, change.field.removeprefix("detail."), change.new)
            continue
        setattr(incident, change.field, change.new)
        if change.reason in ("shared_toll", "unclassified_action"):
            incident.verification_status = "needs_verification"
    if any(c.reason in ("shared_toll", "unclassified_action") for c in plan.changes):
        new["verification_status"] = "needs_verification"
    record_incident_change(
        db,
        incident_id=incident.id,
        action=UpdateAction.edit,
        old_values=old,
        new_values={**new, "channel_header_casualty_cleanup": True},
        performed_by=None,
    )
    db.add(incident)
    if detail is not None:
        db.add(detail)


def run(*, apply: bool = False, reextract: bool = False, session_factory=None, csv_path: Path = OUT_CSV) -> dict[str, Any]:
    if session_factory is None:
        from app.core.database import SessionLocal as session_factory  # noqa: N813
    summary: dict[str, Any] = {"processed": 0, "succeeded": 0, "failed": 0}
    with session_factory() as db:
        supports = _build_reextractor() if reextract else None
        plans = collect_plans(db, reextract_supports=supports)
        summary["processed"] = len(plans)
        path = write_csv(plans, csv_path)
        counts = summarize(plans)
        summary.update({key: counts.get(key, 0) for key in ("kept", "cleared", "status_fixed", "newly_flagged", "needs_review")})
        summary["skipped_admin_edited"] = counts.get("skipped_admin_edited", 0)
        summary["skipped_verified"] = counts.get("skipped_verified", 0)
        summary["csv"] = str(path)
        changed = [plan for plan in plans if plan.changes and not plan.skipped]
        if not apply:
            db.rollback()
            summary["succeeded"] = summary["processed"]
            summary["mode"] = "dry-run (nothing written; pass --apply after reviewing the CSV)"
            return summary
        failed = 0
        for plan in changed:
            try:
                with db.begin_nested():
                    apply_plan(db, plan)
            except Exception:
                failed += 1
                logger.exception("backfill failed for incident %s", plan.incident_id)
        db.commit()
        summary["failed"] = failed
        summary["succeeded"] = summary["processed"] - failed
        summary["mode"] = "applied"
    return summary


def _build_reextractor():
    """``--reextract``: ask Tier 1 again on the stripped body; True if it supports the kind."""
    from app.api.factories.action_factory import build_extraction_classifier

    classifier = build_extraction_classifier()

    def supports(sources: list[ConnectedCasualtySource], kind: str) -> bool:
        for source in sources:
            body = _body(source.text)
            if not body:
                continue
            result = classifier.extract_tier1(post_text=body, raw_message_id=source.raw_message_id)
            casualties = result.casualties
            if _is_positive(getattr(casualties, kind, None)) or _is_positive(getattr(casualties, f"total_{kind}", None)):
                return True
        return False

    return supports


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry-run)")
    parser.add_argument("--reextract", action="store_true", help="allow Tier 1 LLM calls to re-check ungrounded values")
    args = parser.parse_args(argv)
    summary = run(apply=args.apply, reextract=args.reextract)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
