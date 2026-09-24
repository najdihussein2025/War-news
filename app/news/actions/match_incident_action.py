from pydantic import ValidationError

from app.llm.services.lebanon_scope_filter import is_non_lebanon_location
from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.interfaces import MatchingServiceInterface
from app.news.interfaces import RawMessageRepositoryInterface
from app.news.interfaces import AirViolationRepositoryInterface

TIER1_IRRELEVANT_REASON = "tier1_extraction: model marked the post is_relevant=false"


class MatchIncidentAction:
    def __init__(
        self,
        raw_messages: RawMessageRepositoryInterface,
        matching_service: MatchingServiceInterface,
        air_violations: AirViolationRepositoryInterface | None = None,
    ) -> None:
        self.raw_messages = raw_messages
        self.matching_service = matching_service
        self.air_violations = air_violations

    def execute(self, raw_message_id: int) -> MatchResultDTO:
        message = self.raw_messages.get_parsed_by_id(raw_message_id)
        if message is None:
            raise LookupError(
                f"Parsed raw_message id={raw_message_id} was not found."
            )
        if message.extraction_result is None:
            raise ValueError(
                f"raw_message id={raw_message_id} has no extraction_result."
            )

        try:
            extraction_result = ExtractionResult.model_validate(
                message.extraction_result
            )
        except ValidationError as exc:
            raise ValueError(
                f"raw_message id={raw_message_id} has an invalid extraction_result."
            ) from exc

        if (
            extraction_result.is_relevant is False
            and not (getattr(message, "raw_payload", None) or {}).get(
                "manual_rejection_override"
            )
        ):
            # Tier 1 itself judged the post irrelevant: reject it the same way
            # the relevance filter does instead of matching/materializing it.
            self.raw_messages.reject_as_tier1_irrelevant(message)
            return MatchResultDTO(
                village_matches=[],
                any_village_low_confidence=False,
                matched_condition_id=None,
                condition_confidence=None,
                condition_match_status=MatchResultStatus.unmatched,
                condition_review_required=False,
                raw_condition_text=TIER1_IRRELEVANT_REASON,
            )

        non_lebanon_marker = is_non_lebanon_location(
            getattr(message, "raw_text", None)
        )
        if non_lebanon_marker is not None:
            result = MatchResultDTO(
                village_matches=[],
                any_village_low_confidence=False,
                matched_condition_id=None,
                condition_confidence=None,
                condition_match_status=MatchResultStatus.unmatched,
                condition_review_required=True,
                raw_condition_text=(
                    "explicit non-Lebanon location marker: "
                    f"{non_lebanon_marker!r}"
                ),
            )
        else:
            result = self.matching_service.match(
                extraction_result,
                cnrs_classification=getattr(message, "cnrs_classification", None),
            )
        # Route air violations before marking matching complete. If routing
        # fails, match_result remains unset and the pipeline can safely retry
        # this message instead of terminalizing it without an AirViolation row.
        if self.air_violations is not None:
            self.air_violations.route_from_match(message, result)
        self.raw_messages.save_match_result(message, result)
        return result
