"""Confidence-tier matcher for emergency-response organizations.

Mirrors the village / condition matching in ``matching_service.py`` — same
``word_similarity()`` backend (via ``EmergencyOrganizationRepository.find_similar``)
and the *exact* tier boundaries reused from that module:

    score >= 0.6          -> matched
    0.35 <= score < 0.6   -> matched_low_confidence (review required)
    score < 0.35          -> unmatched
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.text_normalization import normalize_arabic_text
from app.news.interfaces import EmergencyOrganizationRepositoryInterface
from app.news.services.matching_service import (
    LOW_CONFIDENCE_THRESHOLD,
    MATCH_THRESHOLD,
)

DEFAULT_CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class EmergencyOrganizationMatch:
    matched_id: int | None
    matched_name_ar: str | None
    matched_name_en: str | None
    matched_org_type: str | None
    confidence: float | None
    status: str  # "matched" | "matched_low_confidence" | "unmatched"
    raw_text: str | None

    @property
    def review_required(self) -> bool:
        return self.status != "matched"


class EmergencyOrganizationMatchingService:
    def __init__(
        self,
        repository: EmergencyOrganizationRepositoryInterface,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        self.repository = repository
        self.candidate_limit = candidate_limit

    def match(self, text: str | None) -> EmergencyOrganizationMatch:
        normalized = normalize_arabic_text(text or "")
        if not normalized:
            return EmergencyOrganizationMatch(
                matched_id=None,
                matched_name_ar=None,
                matched_name_en=None,
                matched_org_type=None,
                confidence=None,
                status="unmatched",
                raw_text=text or None,
            )

        candidates = self.repository.find_similar(normalized, self.candidate_limit)
        if not candidates:
            return EmergencyOrganizationMatch(
                matched_id=None,
                matched_name_ar=None,
                matched_name_en=None,
                matched_org_type=None,
                confidence=None,
                status="unmatched",
                raw_text=text,
            )

        org, raw_score = candidates[0]
        score = max(0.0, min(float(raw_score), 1.0))

        if score >= MATCH_THRESHOLD:
            status = "matched"
        elif score >= LOW_CONFIDENCE_THRESHOLD:
            status = "matched_low_confidence"
        else:
            return EmergencyOrganizationMatch(
                matched_id=None,
                matched_name_ar=None,
                matched_name_en=None,
                matched_org_type=None,
                confidence=score,
                status="unmatched",
                raw_text=text,
            )

        return EmergencyOrganizationMatch(
            matched_id=org.id,
            matched_name_ar=org.name_ar,
            matched_name_en=org.name_en,
            matched_org_type=org.org_type,
            confidence=score,
            status=status,
            raw_text=text,
        )
