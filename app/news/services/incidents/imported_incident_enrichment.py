from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.api.factories.action_factory import build_match_incident_action
from app.core.database import SessionLocal
from app.news.models import Incident, IncidentDetail, RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)
from app.news.services.pipeline.pipeline_llm_workers import (
    run_tier1_extraction_for_message,
    run_tier2_detail_fill_for_message,
)

logger = logging.getLogger(__name__)


def enrich_imported_incidents(raw_message_ids: list[int]) -> None:
    """Immediately enrich the incident rows created by one workbook upload.

    Flow: Tier 1 → match → retire excel stubs → materialize (one row per
    village/event) → Tier 2 detail fill. Each row is isolated so a temporary
    LLM or matching failure leaves that row queued for the normal pipeline
    worker without blocking the others.
    """
    for raw_message_id in raw_message_ids:
        try:
            run_tier1_extraction_for_message(raw_message_id)
            with SessionLocal() as db:
                build_match_incident_action(db).execute(raw_message_id)
            with SessionLocal() as db:
                _materialize_excel_import(db, raw_message_id)
            run_tier2_detail_fill_for_message(raw_message_id)
        except Exception:
            logger.exception(
                "Automatic Excel incident enrichment failed raw_message_id=%s; "
                "the pipeline worker will retry it",
                raw_message_id,
            )


def _materialize_excel_import(db, raw_message_id: int) -> None:
    raw_message = db.get(RawMessage, raw_message_id)
    if raw_message is None:
        raise LookupError(f"raw_message id={raw_message_id} was not found.")
    if raw_message.match_result is None:
        raise ValueError(f"raw_message id={raw_message_id} has no match_result.")

    payload = dict(raw_message.raw_payload or {})
    if payload.get("origin") == "incident_excel_import":
        _retire_excel_placeholders(db, raw_message)

    incident_repo = IncidentRepository(db)
    dedup_service = DedupMatchingService(incident_repository=incident_repo)
    created = IncidentMaterializationService(
        db, dedup_service=dedup_service
    ).materialize(raw_message)

    meta = (raw_message.raw_payload or {}).get("import_metadata") or {}
    if meta and created:
        _apply_import_metadata(db, raw_message_id, meta)
    db.commit()


def _retire_excel_placeholders(db, raw_message: RawMessage) -> None:
    """Remove workbook stubs so materialization owns per-village rows.

    Stashes operator fields (NOTE, MOH, links, …) onto raw_payload so fan-out
    rows can inherit them after materialization.
    """
    incidents = list(
        db.scalars(
            select(Incident).where(Incident.raw_message_id == raw_message.id)
        ).all()
    )
    if not incidents:
        return

    stub = incidents[0]
    payload = dict(raw_message.raw_payload or {})
    payload["import_metadata"] = {
        "note": stub.note,
        "note_extra": stub.note_extra,
        "note_extra_2": stub.note_extra_2,
        "moh": stub.moh,
        "martyrs": stub.martyrs,
        "worker_name": stub.worker_name,
        "source_link": stub.source_link,
        "source_link_2": stub.source_link_2,
        "event_month": stub.event_month,
        "created_by": str(stub.created_by) if stub.created_by else None,
    }
    raw_message.raw_payload = payload
    db.add(raw_message)

    for incident in incidents:
        detail = db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
        )
        if detail is not None:
            db.delete(detail)
        db.delete(incident)
    db.flush()


def _apply_import_metadata(db, raw_message_id: int, meta: dict) -> None:
    created_by = None
    raw_created_by = meta.get("created_by")
    if isinstance(raw_created_by, str) and raw_created_by:
        try:
            created_by = UUID(raw_created_by)
        except ValueError:
            created_by = None

    for incident in db.scalars(
        select(Incident).where(
            Incident.raw_message_id == raw_message_id,
            Incident.is_deleted.is_(False),
        )
    ).all():
        # Import NOTE (e.g. ACCSTUDY-005) must win over materialization notes.
        if meta.get("note"):
            incident.note = meta["note"]
        if meta.get("note_extra"):
            incident.note_extra = meta["note_extra"]
        if meta.get("note_extra_2"):
            incident.note_extra_2 = meta["note_extra_2"]
        if meta.get("moh") and not incident.moh:
            incident.moh = meta["moh"]
        if meta.get("martyrs") and not incident.martyrs:
            incident.martyrs = meta["martyrs"]
        if meta.get("worker_name") and not incident.worker_name:
            incident.worker_name = meta["worker_name"]
        if meta.get("source_link") and not incident.source_link:
            incident.source_link = meta["source_link"]
        if meta.get("source_link_2") and not incident.source_link_2:
            incident.source_link_2 = meta["source_link_2"]
        if meta.get("event_month") and not incident.event_month:
            incident.event_month = meta["event_month"]
        if created_by is not None and incident.created_by is None:
            incident.created_by = created_by
        db.add(incident)
