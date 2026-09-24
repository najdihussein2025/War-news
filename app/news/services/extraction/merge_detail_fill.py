"""Tier 2 detail fill for categories introduced by a pipeline merge.

``merge_existing`` flips ``details_pending`` when a merged report brings new
presence categories, but that report is marked ``duplicate`` and never gets an
incident of its own, so the normal per-raw-message Tier 2 pass (which re-reads
the incident's *original* extraction) could never fill them. This module runs
Tier 2 on each merged-in source message once, and also covers incidents with no
raw message (manual/imported) that were flipped to ``details_pending``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.llm.dtos import ExtractionCategory, ExtractionCategoryKey, ExtractionResult
from app.news.models import (
    Incident,
    IncidentDetail,
    IncidentUpdate,
    RawMessage,
    UpdateAction,
)
from app.news.services.incident_details.category_mapper import map_categories
from app.news.services.incident_details.incident_detail_merge import (
    merge_incident_detail_fields,
)
from app.news.services.incidents.incident_change_log import record_incident_change

logger = logging.getLogger(__name__)

MERGE_FILL_MARKER = "merge_detail_fill_source_raw_message_id"


@dataclass(frozen=True)
class MergeSource:
    raw_message_id: int
    post_text: str
    extraction: ExtractionResult


def pending_merge_sources(db, incident: Incident) -> list[MergeSource]:
    """Merged-in messages with presence categories not yet detail-filled."""
    merged_ids = [
        int(value)
        for value in db.scalars(
            select(
                IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext
            ).where(
                IncidentUpdate.incident_id == incident.id,
                IncidentUpdate.action == UpdateAction.pipeline_merge,
                IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext.is_not(
                    None
                ),
            )
        ).all()
        if value and str(value).isdigit()
    ]
    already_filled = {
        int(value)
        for value in db.scalars(
            select(IncidentUpdate.new_values[MERGE_FILL_MARKER].astext).where(
                IncidentUpdate.incident_id == incident.id,
                IncidentUpdate.new_values[MERGE_FILL_MARKER].astext.is_not(None),
            )
        ).all()
        if value and str(value).isdigit()
    }
    sources: list[MergeSource] = []
    for raw_message_id in dict.fromkeys(merged_ids):
        if raw_message_id == incident.raw_message_id or raw_message_id in already_filled:
            continue
        message = db.get(RawMessage, raw_message_id)
        if message is None or message.extraction_result is None:
            continue
        extraction = ExtractionResult.model_validate(message.extraction_result)
        if not extraction.presence_category_keys:
            continue
        sources.append(
            MergeSource(
                raw_message_id=raw_message_id,
                post_text=message.raw_text or "",
                extraction=extraction,
            )
        )
    return sources


def apply_merge_source_categories(
    db,
    incident: Incident,
    source: MergeSource,
    categories: dict[ExtractionCategoryKey, ExtractionCategory],
    *,
    emergency_org_matcher=None,
) -> None:
    """Merge one source's Tier 2 categories into the incident and mark it filled."""
    detail = db.scalar(
        select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
    )
    if detail is None:
        detail = IncidentDetail(incident_id=incident.id)
        db.add(detail)
        db.flush()
    mapped = map_categories(categories, emergency_org_matcher=emergency_org_matcher)
    merge_incident_detail_fields(detail, mapped)
    db.add(detail)
    record_incident_change(
        db,
        incident_id=incident.id,
        action=UpdateAction.pipeline_merge,
        old_values=None,
        new_values={
            MERGE_FILL_MARKER: source.raw_message_id,
            "categories": sorted(key.value for key in categories),
        },
        performed_by=None,
    )


def run_merge_detail_fill_for_incident(incident_id: UUID, classifier) -> int:
    """Fill categories from merged-in sources; clears details_pending when done.

    No DB session is held during the Ollama calls. Returns sources filled.
    """
    with SessionLocal() as db:
        incident = db.get(Incident, incident_id)
        if incident is None or incident.is_deleted:
            return 0
        sources = pending_merge_sources(db, incident)

    filled: list[tuple[MergeSource, dict]] = []
    for source in sources:
        categories = classifier.extract_tier2_details(
            post_text=source.post_text,
            presence_category_keys=source.extraction.presence_category_keys,
            root_casualties=source.extraction.casualties,
            villages=source.extraction.village,
            casualty_scope=source.extraction.casualty_scope.value,
            raw_message_id=source.raw_message_id,
        )
        filled.append((source, categories))

    with SessionLocal() as db:
        incident = db.get(Incident, incident_id)
        if incident is None or incident.is_deleted:
            return 0
        from app.news.repositories.emergency_organization_repository import (
            EmergencyOrganizationRepository,
        )
        from app.news.services.matching.emergency_organization_matching_service import (
            EmergencyOrganizationMatchingService,
        )

        matcher = EmergencyOrganizationMatchingService(
            EmergencyOrganizationRepository(db)
        )
        for source, categories in filled:
            apply_merge_source_categories(
                db,
                incident,
                source,
                categories,
                emergency_org_matcher=matcher,
            )
        incident.details_pending = False
        db.add(incident)
        db.commit()
    if filled:
        logger.info(
            "merge_detail_fill incident_id=%s sources=%s",
            incident_id,
            [source.raw_message_id for source, _ in filled],
        )
    return len(filled)
