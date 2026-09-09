from __future__ import annotations


def _verification_reason(
    match_result: dict | None,
    *,
    duplicate_flag: bool = False,
    duplicate_level: str | None = None,
    duplicate_similarity_score: float | None = None,
    relevance_needs_review: bool = False,
    relevance_confidence: float | None = None,
    relevance_reasoning: str | None = None,
    insufficient_score: bool = False,
    possible_missed_casualty_transition: bool = False,
    casualty_backstop_keywords: tuple[str, ...] | None = None,
) -> str | None:
    """Return a plain-language review reason from uncertainty signals."""
    result = match_result or {}
    clauses: list[str] = []

    if duplicate_flag:
        if duplicate_level is not None and duplicate_similarity_score is not None:
            clauses.append(
                "Possible duplicate of an existing incident "
                f"(similarity {duplicate_level}, score {duplicate_similarity_score:.2f})."
            )
        else:
            clauses.append(
                "Possible duplicate of an existing incident — flagged during "
                "fast-path matching."
            )
    elif insufficient_score:
        clauses.append(
            "Possible duplicate of an existing incident — flagged during "
            "fast-path matching."
        )

    if relevance_needs_review:
        if relevance_confidence is not None and relevance_reasoning:
            clauses.append(
                "Initial relevance check was uncertain "
                f"(confidence {relevance_confidence:.2f}): {relevance_reasoning}"
            )
        elif relevance_confidence is not None:
            clauses.append(
                "Initial relevance check was uncertain "
                f"(confidence {relevance_confidence:.2f})."
            )
        elif relevance_reasoning:
            clauses.append(
                f"Initial relevance check was uncertain: {relevance_reasoning}"
            )
        else:
            clauses.append("Initial relevance check was uncertain.")

    if possible_missed_casualty_transition:
        clause = (
            "Casualty count may be incomplete — message may describe someone "
            "whose status changed (injured → died) that wasn't fully captured."
        )
        if casualty_backstop_keywords:
            clause += f" Matched terms: {', '.join(casualty_backstop_keywords)}."
        clauses.append(clause)

    condition_status = result.get("condition_match_status")
    if match_result is not None and condition_status != "matched":
        condition_text = result.get("raw_condition_text")
        condition_confidence = result.get("condition_confidence")
        if condition_status == "matched_low_confidence":
            confidence = (
                f"{condition_confidence:.0%}"
                if condition_confidence is not None
                else "unknown"
            )
            if condition_text:
                clauses.append(
                    f"Incident type matched at {confidence} confidence — verify "
                    f"'{condition_text}' is really this category."
                )
            else:
                clauses.append(
                    f"Incident type matched at {confidence} confidence — verify "
                    "this category."
                )
        elif condition_status == "unmatched" or result.get("matched_condition_id") is None:
            if condition_text:
                clauses.append(
                    "Could not confidently match an incident type for "
                    f"'{condition_text}'."
                )
            else:
                clauses.append("Could not confidently match an incident type.")

    for village in result.get("village_matches") or []:
        if village.get("village_role", "target") != "target":
            continue
        village_status = village.get("village_match_status")
        if village_status == "matched":
            continue
        village_text = village.get("raw_village_text")
        if village_status == "matched_low_confidence":
            village_confidence = village.get("village_confidence")
            confidence = (
                f"{village_confidence:.0%}"
                if village_confidence is not None
                else "unknown"
            )
            if village_text:
                clauses.append(
                    f"Village matched at {confidence} confidence — verify "
                    f"'{village_text}' is the right location."
                )
            else:
                clauses.append(
                    f"Village matched at {confidence} confidence — verify the "
                    "right location."
                )
        else:
            if village_text:
                clauses.append(
                    f"Could not confidently match a village for '{village_text}'."
                )
            else:
                clauses.append("Could not confidently match a village.")

    return " | ".join(clauses) if clauses else None
