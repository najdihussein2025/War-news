from __future__ import annotations

from types import SimpleNamespace

from app.news.models import MessageStatus
from app.news.services.pre_extraction_dedup import (
    choose_pre_dedup_original_id,
    is_valid_pre_dedup_original,
)


def test_choose_pre_dedup_original_id_prefers_lower_id() -> None:
    assert choose_pre_dedup_original_id(712, 711) == 711
    assert choose_pre_dedup_original_id(711, 712) is None


def test_is_valid_pre_dedup_original_rejects_duplicate_target() -> None:
    class _Session:
        def get(self, _model, pk: int):
            return SimpleNamespace(
                id=711,
                status=MessageStatus.duplicate,
                duplicate_of_id=700,
            )

    assert (
        is_valid_pre_dedup_original(
            _Session(),  # type: ignore[arg-type]
            candidate_id=712,
            original_id=711,
        )
        is False
    )


def test_is_valid_pre_dedup_original_rejects_two_cycle() -> None:
    class _Session:
        def get(self, _model, pk: int):
            return SimpleNamespace(
                id=711,
                status=MessageStatus.parsed,
                duplicate_of_id=712,
            )

    assert (
        is_valid_pre_dedup_original(
            _Session(),  # type: ignore[arg-type]
            candidate_id=712,
            original_id=711,
        )
        is False
    )
