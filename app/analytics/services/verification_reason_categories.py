"""Group the free-text ``incidents.verification_reason`` into a few stable categories.

The pipeline writes a sentence per reason (sometimes several joined with "; "), and
admins can type their own. The first matching prefix wins, so order matters: put the
specific prefixes first. ``case_sql`` renders the same table as a SQL ``CASE`` so the
Data quality tab groups in the database, never row by row in Python.
"""
from __future__ import annotations

# (category code, label, reason prefixes matched case-insensitively at the start)
CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("unclassified_action", "Action could not be classified", ("Action could not be classified",)),
    ("low_confidence_condition", "Low-confidence action match", (
        "Low-confidence condition text match", "Source metadata fallback",
    )),
    ("low_confidence_village", "Low-confidence village match", ("Low-confidence village match",)),
    ("possible_duplicate", "Possible duplicate", ("Possible duplicate", "100% similar", "duplicated")),
    ("flare_and_strike", "Flare and strike wording", ("Flare wording",)),
    ("shared_casualty_toll", "Shared casualty toll to distribute", (
        "Shared casualty toll", "Unsupported casualty_scope",
    )),
)
NO_REASON = ("no_reason", "No reason recorded")
OTHER = ("other", "Other / admin note")

LABELS: dict[str, str] = {code: label for code, label, _ in CATEGORIES} | dict([NO_REASON, OTHER])


def categorize(reason: str | None) -> str:
    """Python reference of :func:`case_sql` (used by the tests)."""
    if reason is None or not reason.strip():
        return NO_REASON[0]
    text = reason.strip().lower()
    for code, _label, prefixes in CATEGORIES:
        if any(text.startswith(p.lower()) for p in prefixes):
            return code
    return OTHER[0]


def _like_prefix(prefix: str) -> str:
    """Literal LIKE prefix: escape the wildcards ("100% similar", "casualty_scope") and quotes."""
    escaped = prefix.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
    return f"'{escaped}%'"


def case_sql(column: str) -> str:
    """SQL ``CASE`` over ``column`` equal to :func:`categorize`. Prefixes are constants, not input."""
    whens = [f"WHEN {column} IS NULL OR btrim({column}) = '' THEN '{NO_REASON[0]}'"]
    for code, _label, prefixes in CATEGORIES:
        likes = " OR ".join(f"lower(btrim({column})) LIKE {_like_prefix(p)}" for p in prefixes)
        whens.append(f"WHEN {likes} THEN '{code}'")
    return "CASE " + " ".join(whens) + f" ELSE '{OTHER[0]}' END"
