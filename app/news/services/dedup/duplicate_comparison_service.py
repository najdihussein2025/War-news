"""Reusable duplicate-comparison verdict service.

This module is deliberately **entity-agnostic**. It does not import ``Incident``,
``RawMessage`` or any repository — it takes two candidate records' time gap and
pre-computed text/embedding similarity and returns a verdict + confidence.

Incident-specific glue (fetching rows, computing ``word_similarity()`` in SQL,
writing ``duplicate_matches``) lives in the callers (``fast_path_dedup.py`` /
``incident_repository.py``) and passes plain numbers into :meth:`compare`.

Thresholds are config-driven (see ``app.core.config.Settings`` –
``dedup_fastpath_*``) so they can be tuned without a code change.

Approved threshold table (same village_id + same condition_id is a required
precondition enforced by the caller for the standard path, not here):

| Time gap        | Text similarity           | Verdict                     |
|-----------------|---------------------------|-----------------------------|
| ≤ 2 minutes     | ≥ 0.80                    | high_confidence_duplicate   |
| ≤ 2 minutes     | ≥ 0.38 and < 0.80         | possible_duplicate          |
| ≤ 30 minutes    | ≥ 0.80                    | high_confidence_duplicate   |
| ≤ 30 minutes    | ≥ 0.65 and < 0.80         | possible_duplicate          |
| ≤ 6 hours       | ≥ 0.80                    | possible_duplicate          |
| > 6 hours       | any                       | distinct                    |

Cross-village modifier (``village_match_uncertain=True``): never returns
``high_confidence_duplicate``. Within ≤ 30 minutes, text ≥
``cross_village_text_min`` (default 0.87) or embedding ≥ ``embedding_high``
yields ``possible_duplicate`` only; outside that window → ``distinct``.

Embedding similarity, when available, may substitute for text similarity:
  * ≥ 0.86 → high_confidence_duplicate (within the ≤ 30 min tiers)
  * ≥ 0.78 → possible_duplicate (within the ≤ 30 min / ≤ 2 min tiers)
  * never used to bypass the 6 hour cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings, settings

Verdict = Literal["distinct", "possible_duplicate", "high_confidence_duplicate"]
SimilarityMethod = Literal["text", "embedding"]

_VERDICT_RANK: dict[Verdict, int] = {
    "distinct": 0,
    "possible_duplicate": 1,
    "high_confidence_duplicate": 2,
}


@dataclass(frozen=True)
class DuplicateComparisonResult:
    verdict: Verdict
    similarity_score: float
    similarity_method: SimilarityMethod
    time_gap_seconds: float


@dataclass(frozen=True)
class DuplicateComparisonConfig:
    """Snapshot of the tunable thresholds, decoupled from the global settings
    object so tests can construct an explicit config."""

    lookup_window_days: int
    gap_near_seconds: float
    gap_mid_seconds: float
    gap_far_seconds: float
    text_near: float
    text_mid: float
    text_high: float
    embedding_possible: float
    embedding_high: float
    cross_village_text_min: float = 0.87

    @classmethod
    def from_settings(cls, source: Settings | None = None) -> "DuplicateComparisonConfig":
        s = source or settings
        return cls(
            lookup_window_days=s.dedup_fastpath_lookup_window_days,
            gap_near_seconds=float(s.dedup_fastpath_gap_near_seconds),
            gap_mid_seconds=float(s.dedup_fastpath_gap_mid_seconds),
            gap_far_seconds=float(s.dedup_fastpath_gap_far_seconds),
            text_near=s.dedup_fastpath_text_near,
            text_mid=s.dedup_fastpath_text_mid,
            text_high=s.dedup_fastpath_text_high,
            embedding_possible=s.dedup_fastpath_embedding_possible,
            embedding_high=s.dedup_fastpath_embedding_high,
            cross_village_text_min=s.dedup_cross_village_text_min,
        )


class DuplicateComparisonService:
    def __init__(self, config: DuplicateComparisonConfig | None = None) -> None:
        self.config = config or DuplicateComparisonConfig.from_settings()

    def compare(
        self,
        *,
        time_gap_seconds: float,
        text_similarity: float | None,
        embedding_similarity: float | None,
        village_match_uncertain: bool = False,
    ) -> DuplicateComparisonResult:
        gap = abs(float(time_gap_seconds))
        cfg = self.config

        if village_match_uncertain:
            return self._cross_village_verdict(
                gap=gap,
                text_similarity=text_similarity,
                embedding_similarity=embedding_similarity,
            )

        # Beyond the 6h cutoff nothing is a duplicate at the incident level, no
        # matter how similar the text/embedding is.
        if gap > cfg.gap_far_seconds:
            return DuplicateComparisonResult(
                verdict="distinct",
                similarity_score=0.0,
                similarity_method="text",
                time_gap_seconds=gap,
            )

        candidates: list[tuple[Verdict, float, SimilarityMethod]] = []
        if text_similarity is not None:
            candidates.append(
                (
                    self._text_verdict(gap, float(text_similarity)),
                    float(text_similarity),
                    "text",
                )
            )
        if embedding_similarity is not None:
            candidates.append(
                (
                    self._embedding_verdict(gap, float(embedding_similarity)),
                    float(embedding_similarity),
                    "embedding",
                )
            )

        if not candidates:
            return DuplicateComparisonResult(
                verdict="distinct",
                similarity_score=0.0,
                similarity_method="text",
                time_gap_seconds=gap,
            )

        verdict, score, method = max(
            candidates, key=lambda c: (_VERDICT_RANK[c[0]], c[1])
        )
        return DuplicateComparisonResult(
            verdict=verdict,
            similarity_score=score,
            similarity_method=method,
            time_gap_seconds=gap,
        )

    def _cross_village_verdict(
        self,
        *,
        gap: float,
        text_similarity: float | None,
        embedding_similarity: float | None,
    ) -> DuplicateComparisonResult:
        """Human-review-only path when village_id disagrees.

        Never returns high_confidence_duplicate. Requires an elevated similarity
        inside the ≤30 minute window.
        """
        cfg = self.config
        if gap > cfg.gap_mid_seconds:
            return DuplicateComparisonResult(
                verdict="distinct",
                similarity_score=0.0,
                similarity_method="text",
                time_gap_seconds=gap,
            )

        candidates: list[tuple[Verdict, float, SimilarityMethod]] = []
        if text_similarity is not None and float(text_similarity) >= cfg.cross_village_text_min:
            candidates.append(
                ("possible_duplicate", float(text_similarity), "text")
            )
        if (
            embedding_similarity is not None
            and float(embedding_similarity) >= cfg.embedding_high
        ):
            candidates.append(
                ("possible_duplicate", float(embedding_similarity), "embedding")
            )
        if not candidates:
            return DuplicateComparisonResult(
                verdict="distinct",
                similarity_score=float(text_similarity or embedding_similarity or 0.0),
                similarity_method="text" if text_similarity is not None else "embedding",
                time_gap_seconds=gap,
            )
        verdict, score, method = max(
            candidates, key=lambda c: (_VERDICT_RANK[c[0]], c[1])
        )
        return DuplicateComparisonResult(
            verdict=verdict,
            similarity_score=score,
            similarity_method=method,
            time_gap_seconds=gap,
        )

    def _text_verdict(self, gap: float, text: float) -> Verdict:
        cfg = self.config
        if gap <= cfg.gap_near_seconds:
            if text >= cfg.text_high:
                return "high_confidence_duplicate"
            if text >= cfg.text_near:
                return "possible_duplicate"
            return "distinct"
        if gap <= cfg.gap_mid_seconds:
            if text >= cfg.text_high:
                return "high_confidence_duplicate"
            if text >= cfg.text_mid:
                return "possible_duplicate"
            return "distinct"
        # gap <= gap_far_seconds (the > far case is handled in compare()).
        # At 6h distance a strong text match is only ever "possible", never
        # high-confidence.
        if text >= cfg.text_high:
            return "possible_duplicate"
        return "distinct"

    def _embedding_verdict(self, gap: float, embedding: float) -> Verdict:
        cfg = self.config
        # Embedding substitution only applies inside the ≤ 30 min tiers.
        if gap <= cfg.gap_mid_seconds:
            if embedding >= cfg.embedding_high:
                return "high_confidence_duplicate"
            if embedding >= cfg.embedding_possible:
                return "possible_duplicate"
            return "distinct"
        return "distinct"
