from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.llm.dtos import ExtractionResult
from app.news.actions.match_incident_action import MatchIncidentAction
from app.news.models import MessageStatus
from app.news.models.raw_message import FAILED_STAGE_RELEVANCE
from app.news.repositories.raw_message_repository import (
    RawMessageRepository,
    extraction_stage_failure_clause,
)


def _compiled(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_extraction_reset_clause_never_matches_relevance_failures() -> None:
    sql = _compiled(extraction_stage_failure_clause())

    # Explicit extraction failures, or legacy rows that already have a verdict.
    assert "raw_messages.failed_stage = 'tier1_extraction'" in sql
    assert "raw_messages.failed_stage IS NULL" in sql
    assert "raw_messages.filter_result IS NOT NULL" in sql
    assert "relevance_filter" not in sql


def test_reset_retryable_extraction_errors_query_is_scoped_by_stage() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    RawMessageRepository(db).reset_retryable_extraction_errors()

    statement = db.scalars.call_args.args[0]
    sql = _compiled(statement)
    assert "failed_stage" in sql
    assert "filter_result IS NOT NULL" in sql


def test_save_error_records_failed_stage() -> None:
    db = MagicMock()
    message = SimpleNamespace(
        status=MessageStatus.pending,
        error_message=None,
        failed_stage=None,
        processing_claim_stage=None,
        processing_claimed_at=None,
        processing_claimed_by=None,
    )

    RawMessageRepository(db).save_error(
        message=message,
        error_message="ConnectError: connection refused",
        failed_stage=FAILED_STAGE_RELEVANCE,
    )

    assert message.status == MessageStatus.error
    assert message.failed_stage == FAILED_STAGE_RELEVANCE


def test_relevance_errors_are_requeued_to_pending_not_parsed() -> None:
    db = MagicMock()
    message = SimpleNamespace(
        status=MessageStatus.error,
        error_message="ConnectError: connection refused",
        failed_stage=FAILED_STAGE_RELEVANCE,
        filter_result=None,
        processing_claim_stage=None,
        processing_claimed_at=None,
        processing_claimed_by=None,
    )
    db.scalars.return_value.all.return_value = [message]

    requeued = RawMessageRepository(db).reset_retryable_relevance_errors()

    assert requeued == 1
    assert message.status == MessageStatus.pending
    assert message.failed_stage is None


def _extraction(is_relevant: bool) -> dict:
    return ExtractionResult(
        is_relevant=is_relevant,
        village=["كفركلا"],
        action_description="قصف مدفعي",
        extraction_tier=1,
        model="test",
        extracted_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    ).model_dump(mode="json")


def test_tier1_is_relevant_false_is_rejected_not_matched() -> None:
    message = SimpleNamespace(
        id=7,
        raw_text="خبر",
        raw_payload={},
        extraction_result=_extraction(is_relevant=False),
    )
    raw_messages = MagicMock()
    raw_messages.get_parsed_by_id.return_value = message
    matching = MagicMock()
    air_violations = MagicMock()

    MatchIncidentAction(raw_messages, matching, air_violations).execute(7)

    raw_messages.reject_as_tier1_irrelevant.assert_called_once_with(message)
    matching.match.assert_not_called()
    air_violations.route_from_match.assert_not_called()
    raw_messages.save_match_result.assert_not_called()


def test_tier1_is_relevant_false_respects_manual_restore() -> None:
    message = SimpleNamespace(
        id=7,
        raw_text="خبر",
        raw_payload={"manual_rejection_override": {"restored_by": "admin"}},
        extraction_result=_extraction(is_relevant=False),
        cnrs_classification=None,
    )
    raw_messages = MagicMock()
    raw_messages.get_parsed_by_id.return_value = message
    matching = MagicMock()

    MatchIncidentAction(raw_messages, matching).execute(7)

    raw_messages.reject_as_tier1_irrelevant.assert_not_called()
    matching.match.assert_called_once()


def test_reject_as_tier1_irrelevant_mirrors_relevance_rejection() -> None:
    db = MagicMock()
    message = SimpleNamespace(
        status=MessageStatus.parsed,
        filter_result={"verdict": "accept"},
        error_message=None,
        processing_claim_stage="matching",
        processing_claimed_at=None,
        processing_claimed_by=None,
    )

    RawMessageRepository(db).reject_as_tier1_irrelevant(message)

    assert message.status == MessageStatus.rejected
    assert message.filter_result["verdict"] == "reject"
    assert message.filter_result["relevance_verdict_before_tier1"] == "accept"
