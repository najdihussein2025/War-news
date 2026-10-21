from __future__ import annotations

import re
from collections.abc import Callable

from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.dtos.match_result_dto import VillageMatchResult
from app.news.interfaces import AirViolationRepositoryInterface
from app.news.models import MessageStatus, RawMessage, Village
from app.news.services.air_violations.air_violation_eligibility import (
    evaluate_air_violation_text,
)
from app.news.services.air_violations.air_violation_routing import (
    record_air_violation_outcome,
)
from app.news.constants.air_violation_conditions import AIR_VIOLATION_DRONE_CONDITION_ID
from app.news.services.air_violations.latin_location_words import latin_location_words, latin_name_in_words

ConditionClassifier = Callable[[str], int | None]
VillageMatcher = Callable[[str, list[Village]], tuple[Village, str] | None]
VillageListMatcher = Callable[[str, list[Village]], list[tuple[Village, str]]]
CAZA_ONLY_ALIASES: dict[str, tuple[str, str | None]] = {
    "bekaa": ("West Bekaa", "البقاع الغربي"),
    "west bekaa": ("West Bekaa", "البقاع الغربي"),
    "west beqaa": ("West Bekaa", "البقاع الغربي"),
    "البقاع": ("West Bekaa", "البقاع الغربي"),
    "الجنوب": ("South Lebanon", "جنوب لبنان"),
    "جنوب لبنان": ("South Lebanon", "جنوب لبنان"),
    "جنوب": ("South Lebanon", "جنوب لبنان"),
    "شمال لبنان": ("Multiple regions", "مناطق متعددة"),
    "القطاع الغربي": ("Multiple regions", "مناطق متعددة"),
    "القطاع الشرقي": ("Multiple regions", "مناطق متعددة"),
    "القطاع الاوسط": ("Multiple regions", "مناطق متعددة"),
    "القطاع الأوسط": ("Multiple regions", "مناطق متعددة"),
}
CAZA_ONLY_ALIASES.update({
    "south lebanon": ("South Lebanon", "جنوب لبنان"),
    "lebanon": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
    "\u0644\u0628\u0646\u0627\u0646": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
})
RED_ZONE_OCR_MARKER = "__RED_ZONE_TEXT__"


class RedAlertAirViolationService:
    """Apply air-violation rules and route a collected message."""

    def __init__(
        self,
        air_violations: AirViolationRepositoryInterface,
        classify_condition: ConditionClassifier,
        match_village: VillageMatcher,
        match_villages: VillageListMatcher | None = None,
    ) -> None:
        self.air_violations = air_violations
        self.classify_condition = classify_condition
        self.match_village = match_village
        self.match_villages = match_villages

    def process(self, message: RawMessage, villages: list[Village]) -> bool:
        text = message.raw_text or ""
        primary_text = self._primary_text(message) or text
        eligibility = evaluate_air_violation_text(text)
        if not eligibility.eligible:
            self.air_violations.discard_for_message(message)
            record_air_violation_outcome(message, eligibility, stage="red_alert")
            return False

        condition_id = self.classify_condition(text)
        if condition_id is None:
            self.air_violations.discard_for_message(message)
            self._reject(message, "No supported air-violation keyword")
            return False

        primary_village_matches = self._combined_village_matches(primary_text, villages)
        primary_village_match = (
            primary_village_matches[0]
            if primary_village_matches
            else self.match_village(primary_text, villages)
        )
        if primary_village_match is not None:
            village_matches = primary_village_matches
            village_match = primary_village_match
        else:
            village_matches = self._combined_village_matches(text, villages)
            village_match = village_matches[0] if village_matches else self.match_village(text, villages)
        if village_match is None:
            caza_en, caza_ar = self._match_caza(primary_text, villages)
            if not (caza_en or caza_ar):
                caza_en, caza_ar = self._match_caza(text, villages)
            # Rule C is satisfied here by the caza: a Red Alert row with no
            # village keeps its region designation, and a row with neither is
            # rejected just below. Rule D needs no check at this point -- a
            # country-level direction never gets past the text rules above.
            if not (caza_en or caza_ar):
                self.air_violations.discard_for_message(message)
                self._reject(message, self._missing_village_reason(message))
                return False
            if condition_id == AIR_VIOLATION_DRONE_CONDITION_ID and caza_en in {
                "Multiple regions", "South Lebanon", "Unknown",
            }:
                self.air_violations.discard_for_message(message)
                self._reject(message, "Surveillance location is not confirmed to one caza")
                return False
            result = self._match_result(
                text=text,
                condition_id=condition_id,
                village=None,
                raw_location=caza_en or caza_ar,
            )
            message.filter_result = self._result(
                message,
                "relevant",
                "Supported air-violation keyword and caza matched",
            )
            message.match_result = result.model_dump(mode="json")
            message.status = MessageStatus.parsed
            wrote_air_violation = self.air_violations.route_from_match(message, result)
            message.status = MessageStatus.routed_air_violation
            message.error_message = "red_alert: routed to air_violations; not an incident"
            return wrote_air_violation

        village, raw_location = village_match
        result = self._match_result(
            text=text,
            condition_id=condition_id,
            village=village,
            villages=[village for village, _raw_location in village_matches] or [village],
            raw_location=raw_location,
        )
        message.filter_result = self._result(
            message,
            "relevant",
            "Supported air-violation keyword and locality matched",
        )
        message.match_result = result.model_dump(mode="json")
        message.status = MessageStatus.parsed
        wrote_air_violation = self.air_violations.route_from_match(message, result)
        message.status = MessageStatus.routed_air_violation
        message.error_message = "red_alert: routed to air_violations; not an incident"
        return wrote_air_violation

    @staticmethod
    def _primary_text(message: RawMessage) -> str | None:
        payload = message.raw_payload or {}
        preview_text = payload.get("preview_text")
        if isinstance(preview_text, str) and preview_text.strip():
            return preview_text
        raw_payload_text = payload.get("raw_text")
        if (
            isinstance(raw_payload_text, str)
            and raw_payload_text.strip()
            and not payload.get("ocr_text")
        ):
            return raw_payload_text
        return None

    def _combined_village_matches(self, text: str, villages: list[Village]) -> list[tuple[Village, str]]:
        safe_matches = self.match_villages(text, villages) if self.match_villages else []
        if RED_ZONE_OCR_MARKER in text:
            # Alias and exact-name matches are unioned: one crop can name some
            # villages by alias and others by their canonical name.
            matches = [
                *safe_matches,
                *self._red_zone_canonical_matches(text, villages),
            ]
        else:
            matches = [
                *safe_matches,
                *self._match_villages(text, villages),
            ]
        unique: dict[int, tuple[Village, str]] = {}
        for village, raw_location in matches:
            current = unique.get(village.id)
            if current is None or len(raw_location or "") > len(current[1] or ""):
                unique[village.id] = (village, raw_location)
        return list(unique.values())

    @staticmethod
    def _red_zone_canonical_matches(text: str, villages: list[Village]) -> list[tuple[Village, str]]:
        """Match canonical Latin village names inside the red-zone crop only.

        Map labels outside the red circle are nearby places, so the full OCR
        text is never searched. Caza names and names shared by more than one
        village are skipped; such alerts stay unmatched and go to review.
        """
        crop_words = latin_location_words(text.rsplit(RED_ZONE_OCR_MARKER, 1)[-1])
        if not crop_words:
            return []
        caza_names = {
            "".join(latin_location_words(village.caza_en))
            for village in villages
            if getattr(village, "caza_en", None)
        } | {"".join(latin_location_words(alias)) for alias in CAZA_ONLY_ALIASES}
        names: dict[str, tuple[list[str], str, set[int]]] = {}
        village_by_id: dict[int, Village] = {}
        for village in villages:
            for name in (
                getattr(village, "ref_name_en", None),
                getattr(village, "acs_name", None),
                getattr(village, "cad_name", None),
            ):
                if not name or re.search(r"[؀-ۿ]", name):
                    continue
                words = latin_location_words(name)
                compact = "".join(words)
                if len(compact) < 4 or compact in caza_names:
                    continue
                names.setdefault(compact, (words, name, set()))[2].add(village.id)
                village_by_id[village.id] = village
        return [
            (village_by_id[next(iter(village_ids))], name)
            for words, name, village_ids in names.values()
            if len(village_ids) == 1 and latin_name_in_words(words, crop_words)
        ]

    @staticmethod
    def _normalize_arabic(value: str) -> str:
        value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
        value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        value = value.replace("ى", "ي").replace("ة", "ه")
        return re.sub(r"[\W_]+", " ", value.casefold()).strip()

    @staticmethod
    def _normalize_latin(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @classmethod
    def _match_villages(cls, text: str, villages: list[Village]) -> list[tuple[Village, str]]:
        normalized_text = cls._normalize_arabic(text)
        normalized_latin_text = cls._normalize_latin(text)
        matches: dict[int, tuple[Village, str]] = {}
        for village in villages:
            names = (
                getattr(village, "ref_name_ar", None),
                getattr(village, "ref_name_en", None),
                getattr(village, "acs_name", None),
                getattr(village, "cad_name", None),
            )
            for name in names:
                if not name:
                    continue
                normalized_name = (
                    cls._normalize_arabic(name)
                    if re.search(r"[\u0600-\u06ff]", name)
                    else cls._normalize_latin(name)
                )
                normalized_source = (
                    normalized_text
                    if re.search(r"[\u0600-\u06ff]", name)
                    else normalized_latin_text
                )
                if len(normalized_name) >= 3 and re.search(
                    rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
                    normalized_source,
                ):
                    current = matches.get(village.id)
                    if current is None or len(name) > len(current[1]):
                        matches[village.id] = (village, name)
        return list(matches.values())

    @staticmethod
    def _match_caza(text: str, villages: list[Village]) -> tuple[str | None, str | None]:
        normalized_text = text.casefold()
        token_text = re.sub(r"[\W_]+", " ", normalized_text).strip()
        names_south_lebanon = "south lebanon" in token_text or "جنوب لبنان" in token_text
        mentioned: set[tuple[str | None, str | None]] = set()
        for village in villages:
            for name in (village.caza_en, village.caza_ar):
                if name and len(name) >= 4 and name.casefold() in normalized_text:
                    mentioned.add((village.caza_en, village.caza_ar))
        for alias, caza in CAZA_ONLY_ALIASES.items():
            if names_south_lebanon and alias in {"lebanon", "لبنان"}:
                continue
            alias_token = re.sub(r"[\W_]+", " ", alias.casefold()).strip()
            if re.search(rf"(?<!\w){re.escape(alias_token)}(?!\w)", token_text):
                mentioned.add(caza)
        if len(mentioned) > 1:
            return "Multiple regions", "مناطق متعددة"
        if len(mentioned) == 1:
            return next(iter(mentioned))
        return None, None

    @staticmethod
    def _missing_village_reason(message: RawMessage) -> str:
        text = (message.raw_text or "").casefold()
        if ("آخر تحديث" in text or "اخر تحديث" in text) and "لبنان" in text:
            return "General multi-area alert; no single village applies"
        if (message.raw_payload or {}).get("ocr_text"):
            return "Location could not be identified reliably from the alert image"
        return "No locality was specified in the Red Alert notice"

    @staticmethod
    def _match_result(
        *,
        text: str,
        condition_id: int,
        village: Village | None,
        raw_location: str | None,
        villages: list[Village] | None = None,
    ) -> MatchResultDTO:
        matched_villages = villages or ([village] if village is not None else [])
        village_matches = (
            [
                VillageMatchResult(
                    matched_village_id=matched_village.id,
                    village_confidence=1.0,
                    village_match_status=MatchResultStatus.matched,
                    village_review_required=False,
                    raw_village_text=raw_location if len(matched_villages) == 1 else (
                        getattr(matched_village, "ref_name_en", None)
                        or getattr(matched_village, "acs_name", None)
                        or getattr(matched_village, "cad_name", None)
                        or getattr(matched_village, "ref_name_ar", None)
                    ),
                )
                for matched_village in matched_villages
            ]
            if matched_villages
            else []
        )
        return MatchResultDTO(
            village_matches=village_matches,
            any_village_low_confidence=False,
            matched_condition_id=condition_id,
            condition_confidence=1.0,
            condition_match_status=MatchResultStatus.matched,
            condition_review_required=False,
            raw_condition_text=text,
        )

    @staticmethod
    def _result(
        message: RawMessage, verdict: str, reasoning: str
    ) -> dict[str, object]:
        return {
            "backend": "red_alert_rules",
            "verdict": verdict,
            "reasoning": reasoning,
            "confidence": 1.0,
            "raw_message_id": message.id,
        }

    def _reject(
        self,
        message: RawMessage,
        reasoning: str,
        *,
        verdict: str = "not_relevant",
        error: str | None = None,
    ) -> None:
        message.filter_result = self._result(message, verdict, reasoning)
        message.status = MessageStatus.rejected
        message.error_message = error

