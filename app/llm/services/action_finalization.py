from __future__ import annotations

import logging


import logging

from app.llm.dtos import ExtractionResult
from app.llm.services.cnrs_extraction_fallback import trusted_cnrs_action
from app.news.services.matching.condition_evidence_override import (
    apply_condition_evidence_override,
    has_flare_language,
    has_strike_language,
)

logger = logging.getLogger(__name__)


FLARE_GUARD_RELABEL_REASON = "relabeled_by_flare_guard"
FLARE_GUARD_REVIEW_REASON = (
    "Flare wording appears together with strike language; verify whether this "
    "message contains both a strike and flare bombs."
)
logger = logging.getLogger(__name__)


def final_action_description(
    post_text: str,
    extracted_action: str | None,
    cnrs_classification: dict | None,
) -> str | None:
    text_action = apply_condition_evidence_override(post_text, extracted_action)
    if (
        extracted_action
        and extracted_action not in {"Bombs", "Unknown"}
        and text_action == "Bombs"
    ):
        return extracted_action
    if text_action:
        return text_action
    return trusted_cnrs_action(cnrs_classification, post_text)


def finalize_extraction_action(
    result: ExtractionResult,
    *,
    post_text: str,
    cnrs_classification: dict | None,
    raw_message_id: int | None = None,
) -> ExtractionResult:
    cnrs_action = trusted_cnrs_action(cnrs_classification, post_text)
    final_action = final_action_description(
        post_text,
        result.action_description,
        cnrs_classification,
    )
    subtype = (
        str((cnrs_classification or {}).get("event_subtype") or "").strip().lower()
        or None
    )
    action_source = (
        "llm_text"
        if final_action and final_action != cnrs_action
        else "cnrs_subtype_fallback"
        if final_action and cnrs_action
        else result.action_source
    )
    if action_source == "cnrs_subtype_fallback":
        logger.info("Using cnrs_subtype_fallback raw_message_id=%s", raw_message_id)
    if action_source == "cnrs_subtype_fallback":
        logger.info("CNRS subtype fallback used raw_message_id=%s", raw_message_id)

    needs_review = result.needs_review
    review_reason = result.review_reason
    if final_action == "Flare Bomb" and (result.action_description or "") == "Bombs":
        review_reason = _append_reason(review_reason, FLARE_GUARD_RELABEL_REASON)
    elif final_action == "Bombs" and has_flare_language(post_text):
        if has_strike_language(post_text):
            needs_review = True
            review_reason = _append_reason(review_reason, FLARE_GUARD_REVIEW_REASON)
        else:
            final_action = "Flare Bomb"
            action_source = "llm_text"
            review_reason = _append_reason(review_reason, FLARE_GUARD_RELABEL_REASON)

    return result.model_copy(
        update={
            "action_description": final_action,
            "action_source": action_source,
            "source_event_subtype": subtype,
            "source_action_hint": cnrs_action,
            "needs_review": needs_review,
            "review_reason": review_reason,
        }
    )


def _append_reason(existing: str | None, reason: str) -> str:
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}; {reason}"
