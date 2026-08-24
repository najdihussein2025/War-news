from pydantic import ValidationError

from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultDTO
from app.news.interfaces import MatchingServiceInterface
from app.news.interfaces import RawMessageRepositoryInterface
from app.news.interfaces import AirViolationRepositoryInterface


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

        result = self.matching_service.match(extraction_result)
        # Route air violations before marking matching complete. If routing
        # fails, match_result remains unset and the pipeline can safely retry
        # this message instead of terminalizing it without an AirViolation row.
        if self.air_violations is not None:
            self.air_violations.route_from_match(message, result)
        self.raw_messages.save_match_result(message, result)
        return result
