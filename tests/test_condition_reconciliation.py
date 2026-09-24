from datetime import datetime, timezone
from types import SimpleNamespace

from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultStatus
from app.news.services.matching.condition_evidence_override import (
    apply_condition_evidence_override,
)
from app.news.services.matching.matching_service import MatchingService


CONDITIONS = {
    "Bombs": (46, 1.0),
    "Sweeping Operations": (18, 1.0),
    "Aerial Sweep": (19, 1.0),
    "Flare Bomb": (9, 1.0),
    "Unclassified / Needs Review": (47, 1.0),
}


class _VillageRepository:
    def find_similar(self, text: str, limit: int = 5):
        return []


class _ConditionRepository:
    def __init__(self, extra: dict[str, tuple[int, float]] | None = None) -> None:
        self.items = {**CONDITIONS, **(extra or {})}

    def find_similar(self, text: str, limit: int = 5):
        if text in self.items:
            candidate_id, score = self.items[text]
            return [(SimpleNamespace(id=candidate_id, action_en=text), score)]
        return []


def _extraction(
    action: str | None,
    *,
    source_hint: str | None = None,
    action_source: str | None = "llm_text",
) -> ExtractionResult:
    return ExtractionResult(
        is_relevant=True,
        village=[],
        action_description=action,
        action_source=action_source,
        source_event_subtype="direct_attack" if source_hint else None,
        source_action_hint=source_hint,
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )


def test_confident_text_condition_wins_without_review() -> None:
    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction("Flare Bomb", source_hint="Flare Bomb")
    )

    assert result.matched_condition_id == 9
    assert result.condition_confidence == 1.0
    assert result.condition_match_status == MatchResultStatus.matched
    assert result.condition_review_required is False


def test_source_fallback_is_capped_and_review_required() -> None:
    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction(None, source_hint="Bombs", action_source="cnrs_subtype_fallback")
    )

    assert result.matched_condition_id == 46
    assert result.condition_confidence == 0.59
    assert result.condition_match_status == MatchResultStatus.matched_low_confidence
    assert result.condition_review_required is True
    assert "Source metadata fallback used" in result.condition_review_reason


def test_text_source_disagreement_is_flagged_without_silent_confidence() -> None:
    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction("Flare Bomb", source_hint="Bombs")
    )

    assert result.matched_condition_id == 9
    assert result.condition_match_status == MatchResultStatus.matched
    assert result.condition_review_required is True
    assert "disagrees with source metadata" in result.condition_review_reason
    assert "Flare Bomb" in result.condition_review_reason
    assert "Bombs" in result.condition_review_reason


def test_no_usable_candidate_becomes_unclassified_review() -> None:
    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction("unmatchable text", source_hint=None)
    )

    assert result.matched_condition_id == 47
    assert result.condition_match_status == MatchResultStatus.matched_low_confidence
    assert result.condition_review_required is True
    assert "No usable" in result.condition_review_reason


def test_mansouri_apache_sweep_no_longer_resolves_to_bombs() -> None:
    text = "تمشيط من الاباتشي استهدف المنصوري"
    action = apply_condition_evidence_override(text, "Bombs")

    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction(action, source_hint="Bombs")
    )

    assert result.matched_condition_id == 19
    assert result.condition_review_required is True
    assert "disagrees with source metadata" in result.condition_review_reason


def test_haddatha_flares_no_longer_resolve_to_bombs() -> None:
    text = "الا حتلال يلقي قنابل مضيئة في محيط حداثا."
    action = apply_condition_evidence_override(text, "Bombs")

    result = MatchingService(_VillageRepository(), _ConditionRepository()).match(
        _extraction(action, source_hint="Bombs")
    )

    assert result.matched_condition_id == 9
    assert result.condition_review_required is True
    assert "disagrees with source metadata" in result.condition_review_reason
