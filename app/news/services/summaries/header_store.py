"""DB adapter for the summary header dictionary (kept out of the pure headers module)."""
from __future__ import annotations

from sqlalchemy import select

from app.news.models.summary_bulletin import SummaryHeaderMapping

from .dtos import HeaderEntry
from .headers import HeaderDictionarySnapshot, default_header_dictionary
from .normalize import normalize_token


def header_dictionary_for_session(session) -> HeaderDictionarySnapshot:
    """YAML dictionary first, then admin-learned ``summary_header_mappings`` rows.

    A reviewed (approved) YAML entry always wins: a learned mapping is only added for a
    header text the YAML does not already approve, so an admin save can never override
    reviewed data. A missing table (migration 0077 not applied) falls back to YAML only.
    """
    base = default_header_dictionary()
    try:
        with session.begin_nested():  # savepoint: must not poison the caller's transaction
            rows = session.execute(
                select(SummaryHeaderMapping.header_text_normalized, SummaryHeaderMapping.condition_ids)
            ).all()
    except Exception:
        return base
    approved = {key for key, entry in base.by_name.items() if entry.status == "approved"}
    learned = [
        HeaderEntry(normalize_token(text), tuple(ids), "approved", "learned")
        for text, ids in rows
        if normalize_token(text) not in approved and ids
    ]
    if not learned:
        return base
    return HeaderDictionarySnapshot((*base.entries, *learned), base.action_cores, base.header_fillers)
