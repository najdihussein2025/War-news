from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Text, or_, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.models import (
    BulletinCasualtyGroup,
    BulletinCasualtyGroupMember,
    Incident,
    IncidentDetail,
    IncidentUpdate,
    RawMessage,
    UpdateAction,
)
from app.news.models.bulletin_casualty_group import BulletinBreakdownStatus
from app.news.models.incident_verification_flag import IncidentVerificationFlag
from app.news.repositories.incident_verification_flag_repository import IncidentVerificationFlagRepository
from app.news.services.casualty_flag_evaluator import CasualtyFlagEvaluator
from app.news.services.incident_details.admin_casualty_validation import (
    AdminCasualtyValidationError,
    CASUALTY_EDIT_FIELDS,
    DEMOGRAPHIC_FIELDS,
    validate_admin_casualties,
)

router = APIRouter(prefix="/api/verification-flags", tags=["verification-flags"])


class ResolutionEntry(BaseModel):
    incident_id: UUID
    total_deaths: int | float | None = None
    total_injuries: int | float | None = None
    male_d: int | float | None = None
    female_d: int | float | None = None
    children_d: int | float | None = None
    male_i: int | float | None = None
    female_i: int | float | None = None
    children_i: int | float | None = None
    unknown_deaths: bool = False
    unknown_injuries: bool = False


class ResolveRequest(BaseModel):
    entries: list[ResolutionEntry] = Field(default_factory=list)
    confirmed_unknown: bool = False
    note: str | None = None
    override: bool = False
    override_reason: str | None = None

class DismissRequest(BaseModel):
    reason: str = Field(min_length=3)


def _visible_query():
    return select(IncidentVerificationFlag).where(
        or_(
            IncidentVerificationFlag.visible_after.is_(None),
            IncidentVerificationFlag.visible_after <= datetime.now(timezone.utc),
        )
    )


def _row(flag: IncidentVerificationFlag, incident: Incident | None = None) -> dict:
    detail = flag.detail or {}
    return {
        "id": flag.id, "incident_id": flag.incident_id,
        "flag_type": flag.flag_type, "reason_code": flag.reason_code,
        "status": flag.status, "severity": flag.severity,
        "summary": detail.get("summary"),
        "evidence_sentence": detail.get("evidence_sentence"),
        "affected_types": detail.get("affected_types", []),
        "village_name": CasualtyFlagEvaluator._location_name(incident) if incident is not None else None,
        "event_date": getattr(incident, "event_date", None),
        "source_name": getattr(getattr(incident, "source", None), "name", None) or detail.get("source_name"),
        "sibling_count": len(detail.get("sibling_incident_ids") or []),
        "created_at": flag.created_at,
        "resolved_at": flag.resolved_at,
        "resolved_by": flag.resolved_by,
        "resolution": flag.resolution,
        "auto_clear_reason": flag.auto_clear_reason,
    }


def _group_key(flag: IncidentVerificationFlag) -> tuple:
    if flag.reason_code == "aggregate_no_breakdown" and flag.source_message_id is not None:
        return (flag.flag_type, flag.reason_code, flag.source_message_id)
    return (flag.flag_type, flag.reason_code, flag.id)


def _grouped_rows(flags: list[IncidentVerificationFlag], incidents: dict[UUID, Incident], flag_status: str | None) -> list[dict]:
    grouped: dict[tuple, list[IncidentVerificationFlag]] = {}
    for flag in flags:
        grouped.setdefault(_group_key(flag), []).append(flag)
    rows: list[dict] = []
    for members in grouped.values():
        group_status = "open" if any(item.status == "open" for item in members) else members[0].status
        if flag_status and group_status != flag_status:
            continue
        visible_members = [item for item in members if item.status == group_status]
        lead = min(visible_members, key=lambda item: item.created_at)
        incident_ids = list(dict.fromkeys(item.incident_id for item in visible_members))
        locations = list(dict.fromkeys(
            CasualtyFlagEvaluator._location_name(incidents[item_id])
            for item_id in incident_ids
            if item_id in incidents and CasualtyFlagEvaluator._location_name(incidents[item_id])
        ))
        row = _row(lead, incidents.get(lead.incident_id))
        row.update({
            "status": group_status,
            "group_size": len(visible_members),
            "incident_ids": incident_ids[:50],
            "locations": locations[:10],
            "sibling_count": max(0, len(visible_members) - 1),
        })
        rows.append(row)
    return rows


def _summary_payload(flags: list[IncidentVerificationFlag]) -> dict:
    rows = _grouped_rows(flags, {}, "open")
    by_reason: dict[str, int] = {}
    for row in rows:
        by_reason[row["reason_code"]] = by_reason.get(row["reason_code"], 0) + 1
    return {"total": len(rows), "by_reason": by_reason}


def _resolution_error(incident_id: UUID | None, field: str, code: str, message: str) -> dict:
    return {"incident_id": str(incident_id) if incident_id else None, "field": field, "code": code, "message": message}


def _validation_response(errors: list[dict]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"errors": errors})


def _open_types(flag: IncidentVerificationFlag) -> set[str]:
    detail = flag.detail or {}
    if flag.reason_code == "count_missing":
        return set(detail.get("affected_types") or [])
    return {kind for kind, value in (detail.get("remaining_total") or {}).items() if isinstance(value, int) and value > 0}


def _entry_fields(entry: ResolutionEntry, *, legacy_unknown: bool = False) -> set[str]:
    return {
        kind for kind in ("deaths", "injuries")
        if getattr(entry, f"total_{kind}") is not None or getattr(entry, f"unknown_{kind}") or legacy_unknown
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db), _user: User = Depends(require_admin)) -> dict:
    flags = list(db.scalars(_visible_query()).all())
    return _summary_payload(flags)


@router.get("")
def list_flags(
    flag_type: str = "casualty_check", reason_code: str | None = None,
    flag_status: str = Query(default="open", alias="status"),
    date_from: date | None = None, date_to: date | None = None, q: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
    sort: Literal["oldest", "newest"] = "oldest",
    db: Session = Depends(get_db), _user: User = Depends(require_admin),
) -> dict:
    query = _visible_query().where(IncidentVerificationFlag.flag_type == flag_type)
    if reason_code: query = query.where(IncidentVerificationFlag.reason_code == reason_code)
    if date_from: query = query.where(IncidentVerificationFlag.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to: query = query.where(IncidentVerificationFlag.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    if q: query = query.where(IncidentVerificationFlag.detail.cast(Text).ilike(f"%{q}%"))
    flags = list(db.scalars(query).all())
    incidents = {i.id: i for i in db.scalars(select(Incident).where(Incident.id.in_([f.incident_id for f in flags]))).all()}
    rows = _grouped_rows(flags, incidents, flag_status)
    rows.sort(key=lambda item: item["created_at"], reverse=sort == "newest")
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size}


def _live_remaining_total(totals: dict, incidents) -> dict[str, int]:
    """Bulletin total minus counts already stored on the sibling rows (same rule as resolve)."""
    return {
        kind: max(totals[kind] - sum((getattr(row, kind) or 0) for row in incidents), 0)
        for kind in ("deaths", "injuries")
        if isinstance(totals.get(kind), int)
    }


@router.get("/{flag_id}")
def get_flag(flag_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_admin)) -> dict:
    flag = db.get(IncidentVerificationFlag, flag_id)
    if flag is None: raise HTTPException(404, "Verification flag was not found.")
    detail = flag.detail or {}
    group_flags = [flag]
    if flag.reason_code == "aggregate_no_breakdown" and flag.source_message_id is not None:
        group_flags = list(db.scalars(_visible_query().where(
            IncidentVerificationFlag.flag_type == flag.flag_type,
            IncidentVerificationFlag.reason_code == flag.reason_code,
            IncidentVerificationFlag.source_message_id == flag.source_message_id,
        )).all())
    sibling_ids = list(dict.fromkeys(
        [item.incident_id for item in group_flags]
        + [UUID(value) for item in group_flags for value in (item.detail or {}).get("sibling_incident_ids", [])]
    ))
    incidents = db.scalars(select(Incident).where(Incident.id.in_(sibling_ids or [flag.incident_id]))).all()
    message = db.get(RawMessage, flag.source_message_id) if flag.source_message_id else None
    snapshot_text = detail.get("message_text")
    if flag.reason_code == "aggregate_no_breakdown":
        detail = {**detail, "remaining_total": _live_remaining_total(detail.get("bulletin_totals") or {}, incidents)}
    return {**_row(flag, next((i for i in incidents if i.id == flag.incident_id), None)), "detail": detail,
            "message_text": getattr(message, "raw_text", None) or snapshot_text,
            "message_snapshot_used": message is None and bool(snapshot_text),
            "group_size": len(group_flags), "incident_ids": sibling_ids[:50],
            "locations": list(dict.fromkeys(name for i in incidents if (name := CasualtyFlagEvaluator._location_name(i))))[:10],
            "incidents": [{
                "id": i.id,
                "village_name": CasualtyFlagEvaluator._location_name(i),
                "total_deaths": i.total_deaths,
                "total_injuries": i.total_injuries,
                **{
                    field: getattr(getattr(i, "details", None), field, None)
                    for field in DEMOGRAPHIC_FIELDS
                },
            } for i in incidents]}


def _legacy_resolve(flag_id: UUID, payload: ResolveRequest, db: Session, user: User) -> dict:
    repo = IncidentVerificationFlagRepository(db)
    flag = repo.get_by_id(flag_id)
    if flag is None or flag.status != "open": raise HTTPException(404, "Open verification flag was not found.")
    allowed = {flag.incident_id, *(UUID(value) for value in (flag.detail or {}).get("sibling_incident_ids", []))}
    entries = list(payload.entries)
    if payload.confirmed_unknown and not entries:
        entries = [ResolutionEntry(incident_id=incident_id) for incident_id in allowed]
    errors: list[dict] = []
    for entry in entries:
        if entry.incident_id not in allowed:
            errors.append(_resolution_error(entry.incident_id, "entries", "not_a_sibling", "Incident does not belong to this casualty check."))
        if flag.reason_code == "count_missing" and entry.incident_id != flag.incident_id:
            errors.append(_resolution_error(entry.incident_id, "entries", "not_a_sibling", "Missing-number checks accept only their own incident."))
        for kind in ("deaths", "injuries"):
            value = getattr(entry, kind)
            if value is not None and (isinstance(value, bool) or not float(value).is_integer() or value < 0):
                code = "negative" if value < 0 else "invalid_integer"
                errors.append(_resolution_error(entry.incident_id, kind, code, f"{kind.title()} must be a non-negative integer."))
            if value is not None and (getattr(entry, f"unknown_{kind}") or payload.confirmed_unknown):
                errors.append(_resolution_error(entry.incident_id, kind, "conflicting_unknown", f"Choose either a {kind} number or unknown, not both."))
    if not entries:
        errors.append(_resolution_error(None, "entries", "required", "Provide at least one entry or confirm unknown."))
    if errors:
        return _validation_response(errors)

    totals = (flag.detail or {}).get("bulletin_totals") or {}
    entries_by_id = {entry.incident_id: entry for entry in entries}
    sibling_rows = list(db.scalars(select(Incident).where(Incident.id.in_(allowed))).all())
    for kind in ("deaths", "injuries"):
        assigned = sum(
            (getattr(entries_by_id[row.id], kind) if row.id in entries_by_id and getattr(entries_by_id[row.id], kind) is not None else getattr(row, kind)) or 0
            for row in sibling_rows
        )
        total = totals.get(kind)
        if isinstance(total, int) and assigned > total:
            offenders = [entry for entry in entries if getattr(entry, kind) is not None]
            errors.extend(_resolution_error(entry.incident_id, kind, "over_total", f"Assigned {kind} ({assigned}) exceeds bulletin total ({total}).") for entry in offenders or entries[:1])
    if errors:
        return _validation_response(errors)

    results: list[dict] = []
    for entry in entries:
        incident = db.get(Incident, entry.incident_id)
        if incident is None: raise HTTPException(404, f"Incident {entry.incident_id} was not found.")
        old, new = {}, {}
        target_flag = next((candidate for candidate in repo.list_open_for_incident(entry.incident_id) if candidate.flag_type == flag.flag_type and candidate.reason_code == flag.reason_code), None)
        if target_flag is None:
            results.append({"incident_id": entry.incident_id, "resolved": False, "still_open": False, "reason": "no_open_flag"})
            continue
        covered = _entry_fields(entry, legacy_unknown=payload.confirmed_unknown)
        open_types = _open_types(target_flag)
        for kind in ("deaths", "injuries"):
            value = getattr(entry, kind)
            if value is not None:
                value = int(value)
                old[kind] = getattr(incident, kind); old[f"total_{kind}"] = getattr(incident, f"total_{kind}")
                new[kind] = value; new[f"total_{kind}"] = value
                setattr(incident, kind, value); setattr(incident, f"total_{kind}", value)
                setattr(incident, f"casualty_{kind}_status", "exact")
            elif getattr(entry, f"unknown_{kind}") or (payload.confirmed_unknown and kind in open_types):
                setattr(incident, f"casualty_{kind}_status", "none_mentioned")
        type_statuses = {incident.casualty_deaths_status, incident.casualty_injuries_status}
        if "aggregate_only" in type_statuses: incident.casualty_status = "aggregate_only"
        elif "count_missing" in type_statuses: incident.casualty_status = "count_missing"
        elif "exact" in type_statuses: incident.casualty_status = "exact"
        else: incident.casualty_status = "none_mentioned"
        remaining = dict(incident.casualty_status_remaining_total or {})
        for kind in ("deaths", "injuries"):
            if kind in covered: remaining.pop(kind, None)
        incident.casualty_status_remaining_total = remaining
        if new:
            db.add(IncidentUpdate(incident_id=incident.id, action=UpdateAction.edit, old_values=old, new_values=new, performed_by=user.id))
        resolution = entry.model_dump(mode="json") | ({"note": payload.note} if payload.note else {})
        if open_types and open_types.issubset(covered):
            repo.resolve_flag(target_flag.id, user.id, resolution)
            results.append({"incident_id": entry.incident_id, "resolved": True, "still_open": False, "reason": "all_open_types_covered"})
        else:
            old_detail = dict(target_flag.detail or {})
            new_detail = dict(old_detail)
            if target_flag.reason_code == "count_missing":
                new_detail["affected_types"] = sorted(open_types - covered)
            else:
                new_detail["remaining_total"] = {kind: value for kind, value in (old_detail.get("remaining_total") or {}).items() if kind not in covered}
            repo.update_open_resolution(target_flag.id, resolution, new_detail)
            results.append({"incident_id": entry.incident_id, "resolved": False, "still_open": True, "reason": "open_types_remain"})
    evaluator = CasualtyFlagEvaluator(db, enabled=True)
    for incident_id in allowed:
        evaluator.evaluate_incident(incident_id)
    db.flush()
    assigned: dict[str, int] = {}
    remaining_total: dict[str, int] = {}
    for kind in ("deaths", "injuries"):
        assigned[kind] = sum((getattr(row, kind) or 0) for row in sibling_rows)
        if isinstance(totals.get(kind), int): remaining_total[kind] = max(totals[kind] - assigned[kind], 0)
    db.commit()
    return {"results": results, "totals": {kind: {"assigned": assigned[kind], "bulletin_total": totals.get(kind)} for kind in ("deaths", "injuries")}, "remaining_total": remaining_total}


def _entry_values(entry: ResolutionEntry) -> dict[str, int | None]:
    raw = entry.model_dump()
    return {field: raw.get(field) for field in CASUALTY_EDIT_FIELDS}


def _apply_casualty_values(
    incident: Incident,
    detail: IncidentDetail,
    values: dict[str, int | None],
) -> tuple[dict, dict]:
    old = {
        "total_deaths": incident.total_deaths,
        "total_injuries": incident.total_injuries,
        **{field: getattr(detail, field) for field in DEMOGRAPHIC_FIELDS},
        "casualty_status": incident.casualty_status,
        "casualty_deaths_status": incident.casualty_deaths_status,
        "casualty_injuries_status": incident.casualty_injuries_status,
        "verification_status": incident.verification_status,
        "verification_reason": incident.verification_reason,
    }
    incident.total_deaths = values["total_deaths"]
    incident.total_injuries = values["total_injuries"]
    # Keep the legacy aggregate columns synchronized with the canonical totals.
    incident.deaths = values["total_deaths"]
    incident.injuries = values["total_injuries"]
    for field in DEMOGRAPHIC_FIELDS:
        setattr(detail, field, values[field])
    incident.casualty_deaths_status = "exact" if values["total_deaths"] is not None else "none_mentioned"
    incident.casualty_injuries_status = "exact" if values["total_injuries"] is not None else "none_mentioned"
    incident.casualty_status = (
        "exact" if values["total_deaths"] is not None or values["total_injuries"] is not None
        else "none_mentioned"
    )
    incident.casualty_status_remaining_total = None
    if old["casualty_status"] in {"count_missing", "aggregate_only"}:
        incident.verification_status = "verified"
        incident.verification_reason = None
    new = {
        "total_deaths": incident.total_deaths,
        "total_injuries": incident.total_injuries,
        **{field: getattr(detail, field) for field in DEMOGRAPHIC_FIELDS},
        "casualty_status": incident.casualty_status,
        "casualty_deaths_status": incident.casualty_deaths_status,
        "casualty_injuries_status": incident.casualty_injuries_status,
        "verification_status": incident.verification_status,
        "verification_reason": incident.verification_reason,
    }
    return old, new


def _distribution_errors(
    values_by_incident: dict[UUID, dict[str, int | None]],
    total_deaths: int | None,
    total_injuries: int | None,
    *,
    override: bool,
) -> tuple[dict[str, int], list[dict]]:
    assigned = {
        "total_deaths": sum(values["total_deaths"] or 0 for values in values_by_incident.values()),
        "total_injuries": sum(values["total_injuries"] or 0 for values in values_by_incident.values()),
    }
    errors = []
    for field, expected in (("total_deaths", total_deaths), ("total_injuries", total_injuries)):
        if expected is not None and assigned[field] != expected and not override:
            errors.append(_resolution_error(
                None, field, "sum_mismatch",
                f"مجموع الأعداد الموزعة ({assigned[field]}) لا يساوي إجمالي النشرة ({expected}).",
            ))
    return assigned, errors


@router.post("/{flag_id}/resolve")
def resolve(flag_id: UUID, payload: ResolveRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    repo = IncidentVerificationFlagRepository(db)
    flag = repo.get_by_id(flag_id)
    if flag is None or flag.status != "open":
        raise HTTPException(404, "Open verification flag was not found.")

    is_group = flag.reason_code == "aggregate_no_breakdown"
    group = None
    member_rows: list[BulletinCasualtyGroupMember] = []
    if is_group:
        member = db.scalar(select(BulletinCasualtyGroupMember).where(
            BulletinCasualtyGroupMember.incident_id == flag.incident_id
        ))
        if member is None:
            raise HTTPException(409, "This casualty group is no longer available.")
        group = db.scalar(
            select(BulletinCasualtyGroup)
            .where(BulletinCasualtyGroup.id == member.group_id)
            .with_for_update()
        )
        if group is None or group.breakdown_status != BulletinBreakdownStatus.pending:
            raise HTTPException(409, "This casualty group was already resolved by another administrator.")
        member_rows = list(db.scalars(
            select(BulletinCasualtyGroupMember)
            .where(BulletinCasualtyGroupMember.group_id == group.id)
            .order_by(BulletinCasualtyGroupMember.ordinal)
        ).all())
        allowed = {row.incident_id for row in member_rows if row.incident_id is not None}
    else:
        allowed = {flag.incident_id}

    entries = payload.entries
    entry_ids = [entry.incident_id for entry in entries]
    errors: list[dict] = []
    if len(entry_ids) != len(set(entry_ids)):
        errors.append(_resolution_error(None, "entries", "duplicate", "Each linked incident may appear only once."))
    if set(entry_ids) != allowed:
        errors.append(_resolution_error(None, "entries", "incomplete_group", "Submit casualty values for every linked incident in one request."))
    if payload.override and not (payload.override_reason or "").strip():
        errors.append(_resolution_error(None, "override_reason", "required", "An override reason is required."))
    if not payload.override and (payload.override_reason or "").strip():
        errors.append(_resolution_error(None, "override_reason", "unexpected", "Enable override before providing an override reason."))

    validated: dict[UUID, dict[str, int | None]] = {}
    for entry in entries:
        raw = _entry_values(entry)
        for field, value in raw.items():
            if value is not None and (isinstance(value, bool) or not float(value).is_integer() or value < 0):
                errors.append(_resolution_error(entry.incident_id, field, "invalid_integer", f"{field} must be a non-negative integer or null."))
        if any(error["incident_id"] == str(entry.incident_id) for error in errors):
            continue
        try:
            validated[entry.incident_id] = validate_admin_casualties({
                field: int(value) if value is not None else None for field, value in raw.items()
            })
        except AdminCasualtyValidationError as exc:
            errors.append(_resolution_error(entry.incident_id, exc.field, "invariant", str(exc)))

    assigned, distribution_errors = _distribution_errors(
        validated,
        getattr(group, "total_deaths", None),
        getattr(group, "total_injuries", None),
        override=payload.override,
    )
    if group is not None:
        errors.extend(distribution_errors)
    if errors:
        return _validation_response(errors)

    incidents = list(db.scalars(
        select(Incident).where(Incident.id.in_(allowed)).with_for_update()
    ).all())
    if {incident.id for incident in incidents} != allowed:
        raise HTTPException(404, "One or more linked incidents were not found.")
    details = {
        detail.incident_id: detail for detail in db.scalars(
            select(IncidentDetail).where(IncidentDetail.incident_id.in_(allowed)).with_for_update()
        ).all()
    }
    now = datetime.now(timezone.utc)
    results: list[dict] = []
    for incident in incidents:
        detail = details.get(incident.id)
        if detail is None:
            detail = IncidentDetail(incident_id=incident.id)
            db.add(detail)
        old, new = _apply_casualty_values(incident, detail, validated[incident.id])
        db.add(IncidentUpdate(
            incident_id=incident.id,
            action=UpdateAction.edit if old != new else UpdateAction.status_change,
            old_values=old,
            new_values={**new, "casualty_resolution": "linked_group" if is_group else "count_missing"},
            performed_by=user.id,
        ))
        for open_flag in repo.list_open_for_incident(incident.id):
            if open_flag.flag_type == flag.flag_type and open_flag.reason_code == flag.reason_code:
                repo.resolve_flag(open_flag.id, user.id, {
                    "entry": next(entry.model_dump(mode="json") for entry in entries if entry.incident_id == incident.id),
                    "note": payload.note,
                    "override": payload.override,
                    "override_reason": payload.override_reason,
                })
        results.append({"incident_id": incident.id, "resolved": True, "still_open": False, "reason": "all_values_saved"})

    if group is not None:
        group.breakdown_status = BulletinBreakdownStatus.resolved
        group.resolved_at = now
        group.total_overridden = payload.override
        group.total_override_reason = payload.override_reason.strip() if payload.override_reason else None
        group.total_override_by_user_id = user.id if payload.override else None
        group.total_override_at = now if payload.override else None
        if payload.override:
            owner_id = group.owner_incident_id or incidents[0].id
            db.add(IncidentUpdate(
                incident_id=owner_id,
                action=UpdateAction.status_change,
                old_values={"group_total_deaths": group.total_deaths, "group_total_injuries": group.total_injuries, "total_overridden": False},
                new_values={"assigned_total_deaths": assigned["total_deaths"], "assigned_total_injuries": assigned["total_injuries"], "total_overridden": True, "override_reason": group.total_override_reason},
                performed_by=user.id,
            ))
    db.flush()
    for incident in incidents:
        CasualtyFlagEvaluator(db, enabled=True).evaluate_incident(incident.id)
    db.commit()
    return {
        "results": results,
        "totals": {
            "deaths": {"assigned": assigned["total_deaths"], "bulletin_total": getattr(group, "total_deaths", None)},
            "injuries": {"assigned": assigned["total_injuries"], "bulletin_total": getattr(group, "total_injuries", None)},
        },
        "remaining_total": {"deaths": 0, "injuries": 0} if group is not None else {},
    }


@router.post("/{flag_id}/dismiss")
def dismiss(flag_id: UUID, payload: DismissRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    try: flag = IncidentVerificationFlagRepository(db).dismiss_flag(flag_id, user.id, payload.reason)
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc
    db.commit(); return _row(flag)
