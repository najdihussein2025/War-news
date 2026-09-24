from __future__ import annotations


LOW_CONFIDENCE_VILLAGE_REVIEW_REASON = (
    "Low-confidence village match requires manual review."
)


def _verification_reason(
    match_result: dict | None,
    *,
    duplicate_flag: bool = False,
    duplicate_level: str | None = None,
    duplicate_similarity_score: float | None = None,
    insufficient_score: bool = False,
    low_confidence_village_match: bool = False,
    condition_review_reason: str | None = None,
) -> str | None:
    """Return a plain-language review reason for unresolved review signals."""
    if condition_review_reason:
        return condition_review_reason
    if low_confidence_village_match:
        return LOW_CONFIDENCE_VILLAGE_REVIEW_REASON
    if duplicate_flag:
        if duplicate_level is not None and duplicate_similarity_score is not None:
            return (
                "Possible duplicate of an existing incident "
                f"(similarity {duplicate_level}, score {duplicate_similarity_score:.2f})."
            )
        return (
            "Possible duplicate of an existing incident — flagged during "
            "fast-path matching."
        )
    if insufficient_score:
        return (
            "Possible duplicate of an existing incident — flagged during "
            "fast-path matching."
        )
    return None
