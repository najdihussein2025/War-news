from __future__ import annotations

import logging

from app.api.factories.action_factory import build_match_incident_action
from app.core.database import SessionLocal
from app.news.services.pipeline_llm_workers import (
    run_tier1_extraction_for_message,
    run_tier2_detail_fill_for_message,
)

logger = logging.getLogger(__name__)


def enrich_imported_incidents(raw_message_ids: list[int]) -> None:
    """Immediately enrich the incident rows created by one workbook upload.

    Each row is isolated so a temporary LLM or matching failure leaves that
    row queued for the normal pipeline worker without blocking the others.
    """
    for raw_message_id in raw_message_ids:
        try:
            run_tier1_extraction_for_message(raw_message_id)
            with SessionLocal() as db:
                build_match_incident_action(db).execute(raw_message_id)
            run_tier2_detail_fill_for_message(raw_message_id)
        except Exception:
            logger.exception(
                "Automatic Excel incident enrichment failed raw_message_id=%s; "
                "the pipeline worker will retry it",
                raw_message_id,
            )
