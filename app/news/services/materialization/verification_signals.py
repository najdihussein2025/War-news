from __future__ import annotations


def _verification_reason(
    match_result: dict | None,
    *,
    duplicate_flag: bool = False,
    duplicate_level: str | None = None,
    duplicate_similarity_score: float | None = None,
    insufficient_score: bool = False,
) -> str | None:
    """Return a plain-language review reason — duplicate signals only."""
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
