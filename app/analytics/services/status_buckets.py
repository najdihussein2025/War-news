"""The single definition of "headline" for every analytics number.

An incident contributes to analytics in one of two buckets, or not at all:

* excluded (no fact row): ``is_deleted`` or ``verification_status = 'rejected'``.
  Deleted and rejected incidents never count anywhere.
* pending: ``verification_status = 'needs_verification'``, or the incident's
  condition belongs to an action family with ``counts_in_headline = false``
  (the unclassified family: "Air Activity - Needs Verification" and
  "Unclassified / Needs Review"). Pending is excluded from the headline by
  default, shown separately, and a UI toggle can include it.
* counted (the headline): everything else, i.e. ``verified`` and
  ``auto_processed``.

Any other status value (the column has a CHECK on the four above, so none
exists today) is treated as pending rather than silently inflating the headline.

``decide_bucket`` is the reference implementation; ``bucket_sql`` renders the
same rule as a SQL expression for the set-based fact builders. Both live in this
file so the rule cannot drift, and the truth-table test evaluates the SQL
against the Python function for every combination.
"""
from __future__ import annotations

from app.analytics.models.facts import BUCKET_COUNTED, BUCKET_PENDING

COUNTED_STATUSES = ("verified", "auto_processed")
PENDING_STATUS = "needs_verification"
REJECTED_STATUS = "rejected"


def decide_bucket(
    verification_status: str | None,
    is_deleted: bool,
    family_counts_in_headline: bool,
) -> str | None:
    """Return ``'counted'``, ``'pending'`` or ``None`` (excluded)."""
    if is_deleted or verification_status == REJECTED_STATUS:
        return None
    if verification_status == PENDING_STATUS or not family_counts_in_headline:
        return BUCKET_PENDING
    if verification_status in COUNTED_STATUSES:
        return BUCKET_COUNTED
    return BUCKET_PENDING


def bucket_sql(status: str, deleted: str, counts_in_headline: str) -> str:
    """SQL ``CASE`` equivalent of :func:`decide_bucket` over the given column names."""
    counted = ", ".join(f"'{value}'" for value in COUNTED_STATUSES)
    return (
        f"CASE "
        f"WHEN {deleted} OR {status} = '{REJECTED_STATUS}' THEN NULL "
        f"WHEN {status} = '{PENDING_STATUS}' OR NOT {counts_in_headline} THEN '{BUCKET_PENDING}' "
        f"WHEN {status} IN ({counted}) THEN '{BUCKET_COUNTED}' "
        f"ELSE '{BUCKET_PENDING}' END"
    )
