from __future__ import annotations

import pytest

from app.news.services.duplicate_comparison_service import (
    DuplicateComparisonConfig,
    DuplicateComparisonService,
)

# Explicit config mirroring the approved defaults so the test does not depend on
# a fully-populated Settings() (which needs database_url / secrets in env).
_CONFIG = DuplicateComparisonConfig(
    lookup_window_days=7,
    gap_near_seconds=120,
    gap_mid_seconds=1800,
    gap_far_seconds=21600,
    text_near=0.38,
    text_mid=0.65,
    text_high=0.80,
    embedding_possible=0.78,
    embedding_high=0.86,
)


@pytest.fixture
def service() -> DuplicateComparisonService:
    return DuplicateComparisonService(_CONFIG)


MIN = 60
HOUR = 3600


@pytest.mark.parametrize(
    ("gap", "text", "expected"),
    [
        # ≤ 2 minutes
        (30, 0.85, "high_confidence_duplicate"),
        (120, 0.80, "high_confidence_duplicate"),
        (90, 0.50, "possible_duplicate"),
        (90, 0.38, "possible_duplicate"),
        (90, 0.37, "distinct"),
        # ≤ 30 minutes
        (10 * MIN, 0.81, "high_confidence_duplicate"),
        (10 * MIN, 0.70, "possible_duplicate"),
        (10 * MIN, 0.65, "possible_duplicate"),
        (10 * MIN, 0.64, "distinct"),
        (10 * MIN, 0.40, "distinct"),  # 0.38 floor is only for the ≤2min tier
        # ≤ 6 hours: strong text is only ever "possible" at this distance
        (3 * HOUR, 0.95, "possible_duplicate"),
        (3 * HOUR, 0.79, "distinct"),
        (6 * HOUR, 0.80, "possible_duplicate"),
        # > 6 hours: always distinct
        (6 * HOUR + 1, 0.99, "distinct"),
        (90 * HOUR, 0.99, "distinct"),
    ],
)
def test_text_only_verdicts(
    service: DuplicateComparisonService, gap: float, text: float, expected: str
) -> None:
    result = service.compare(
        time_gap_seconds=gap, text_similarity=text, embedding_similarity=None
    )
    assert result.verdict == expected
    assert result.similarity_method == "text"
    assert result.time_gap_seconds == gap


@pytest.mark.parametrize(
    ("gap", "embedding", "expected"),
    [
        (30, 0.90, "high_confidence_duplicate"),
        (30, 0.80, "possible_duplicate"),
        (30, 0.77, "distinct"),
        (10 * MIN, 0.86, "high_confidence_duplicate"),
        (10 * MIN, 0.78, "possible_duplicate"),
        (10 * MIN, 0.70, "distinct"),
        # Beyond ≤30min, embedding cannot create a verdict...
        (3 * HOUR, 0.99, "distinct"),
        # ...and never bypasses the 6h cutoff.
        (7 * HOUR, 0.99, "distinct"),
    ],
)
def test_embedding_substitution(
    service: DuplicateComparisonService, gap: float, embedding: float, expected: str
) -> None:
    result = service.compare(
        time_gap_seconds=gap, text_similarity=None, embedding_similarity=embedding
    )
    assert result.verdict == expected


def test_strongest_signal_wins(service: DuplicateComparisonService) -> None:
    # Text says distinct, embedding says possible -> possible, method=embedding.
    result = service.compare(
        time_gap_seconds=60, text_similarity=0.10, embedding_similarity=0.80
    )
    assert result.verdict == "possible_duplicate"
    assert result.similarity_method == "embedding"

    # Text says high-confidence, embedding weak -> high-confidence, method=text.
    result = service.compare(
        time_gap_seconds=60, text_similarity=0.90, embedding_similarity=0.10
    )
    assert result.verdict == "high_confidence_duplicate"
    assert result.similarity_method == "text"


def test_no_signals_is_distinct(service: DuplicateComparisonService) -> None:
    result = service.compare(
        time_gap_seconds=60, text_similarity=None, embedding_similarity=None
    )
    assert result.verdict == "distinct"
    assert result.similarity_score == 0.0


def test_negative_gap_is_treated_as_magnitude(
    service: DuplicateComparisonService,
) -> None:
    result = service.compare(
        time_gap_seconds=-90, text_similarity=0.85, embedding_similarity=None
    )
    assert result.verdict == "high_confidence_duplicate"
    assert result.time_gap_seconds == 90


# --- Regression scenarios from the Phase 1 spec (service-level) ---------------


def test_mansouri_style_pair_is_not_a_duplicate(
    service: DuplicateComparisonService,
) -> None:
    """Same village/condition, ~81-94h gap, text similarity 0.19-0.57 -> distinct."""
    for gap_hours in (81, 88, 94):
        for text in (0.19, 0.38, 0.57):
            result = service.compare(
                time_gap_seconds=gap_hours * HOUR,
                text_similarity=text,
                embedding_similarity=0.60,
            )
            assert result.verdict == "distinct", (gap_hours, text)


def test_nabatiyeh_style_set_flags_as_duplicate(
    service: DuplicateComparisonService,
) -> None:
    """Same village/condition, ~2min gaps, high text similarity -> duplicate."""
    for gap_seconds in (30, 60, 110, 120):
        result = service.compare(
            time_gap_seconds=gap_seconds,
            text_similarity=0.88,
            embedding_similarity=None,
        )
        assert result.verdict == "high_confidence_duplicate"


def test_config_from_settings_matches_approved_defaults() -> None:
    """Guards against silent drift of the shipped defaults."""
    from app.core.config import settings

    cfg = DuplicateComparisonConfig.from_settings(settings)
    assert cfg.gap_near_seconds == 120
    assert cfg.gap_mid_seconds == 1800
    assert cfg.gap_far_seconds == 21600
    assert cfg.text_near == 0.38
    assert cfg.text_mid == 0.65
    assert cfg.text_high == 0.80
    assert cfg.embedding_possible == 0.78
    assert cfg.embedding_high == 0.86
