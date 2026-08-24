from __future__ import annotations

from collections.abc import Callable

from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.dtos.match_result_dto import VillageMatchResult
from app.news.interfaces import AirViolationRepositoryInterface
from app.news.models import MessageStatus, RawMessage, Village

ConditionClassifier = Callable[[str], int | None]
VillageMatcher = Callable[[str, list[Village]], tuple[Village, str] | None]


class RedAlertAirViolationService:
    """Apply air-violation rules and route a collected message."""

    def __init__(
        self,
        air_violations: AirViolationRepositoryInterface,
        classify_condition: ConditionClassifier,
        match_village: VillageMatcher,
    ) -> None:
        self.air_violations = air_violations
        self.classify_condition = classify_condition
        self.match_village = match_village

    def process(self, message: RawMessage, villages: list[Village]) -> bool:
        text = message.raw_text or ""
        condition_id = self.classify_condition(text)
        if condition_id is None:
            self.air_violations.discard_for_message(message)
            self._reject(message, "No supported air-violation keyword")
            return False

        village_match = self.match_village(text, villages)
        village, raw_location = village_match if village_match is not None else (None, None)
        result = self._match_result(
            text=text,
            condition_id=condition_id,
            village=village,
            raw_location=raw_location,
        )
        message.filter_result = self._result(
            message,
            "relevant",
            "Supported air-violation keyword and locality matched",
        )
        message.match_result = result.model_dump(mode="json")
        message.status = MessageStatus.parsed
        self.air_violations.route_from_match(message, result)
        message.status = MessageStatus.error
        message.error_message = "red_alert: routed to air_violations; not an incident"
        return True

    @staticmethod
    def _match_result(
        *,
        text: str,
        condition_id: int,
        village: Village | None,
        raw_location: str | None,
    ) -> MatchResultDTO:
        village_matches = (
            [
                VillageMatchResult(
                    matched_village_id=village.id,
                    village_confidence=1.0,
                    village_match_status=MatchResultStatus.matched,
                    village_review_required=False,
                    raw_village_text=raw_location,
                )
            ]
            if village is not None
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
