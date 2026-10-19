from pydantic import ValidationError

from app.llm.services.lebanon_scope_filter import is_non_lebanon_location
from app.llm.dtos import ExtractionResult, ExtractionSubEvent
from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.interfaces import MatchingServiceInterface
from app.news.interfaces import RawMessageRepositoryInterface
from app.news.interfaces import AirViolationRepositoryInterface
from app.news.constants.air_violation_conditions import AIR_VIOLATION_CONDITION_IDS
from app.news.services.air_violations.air_violation_routing import (
    record_air_violation_outcome,
)
from app.news.services.air_violations.air_violation_eligibility import (
    evaluate_air_violation_text,
)
from app.news.services.matching.condition_evidence_override import (
    condition_fallback_from_text,
    explicit_condition_labels_from_text,
)
from app.news.services.matching.location_ownership_rules import (
    apply_location_ownership_rules,
)

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

        extraction_result = apply_location_ownership_rules(
            extraction_result,
            getattr(message, "raw_text", None),
        )

        raw_text = getattr(message, "raw_text", None)
        source_conditions = explicit_condition_labels_from_text(raw_text)
        target_locations = (
            extraction_result.sub_events[0].locations
            if len(extraction_result.sub_events) == 1
            else extraction_result.village_roles
        )
        if len(source_conditions) > 1 and len(target_locations) == 1:
            # One source can state multiple distinct actions at the same
            # village. Preserve each action as a separate event instead of
            # collapsing them into one generic condition.
            extraction_result = extraction_result.model_copy(
                update={
                    "sub_events": [
                        ExtractionSubEvent(
                            locations=list(target_locations),
                            action_text=condition,
                            evidence_span=raw_text,
                        )
                        for condition in source_conditions
                    ],
                    "action_description": source_conditions[0],
                    "action_source": "keyword_fallback",
                }
            )
        else:
            # Prefer explicit source evidence over a broad model-generated
            # action label; e.g. Arabic "تفجير" is Mining & Detonation, not
            # the generic Bombs category.
            source_condition = condition_fallback_from_text(raw_text)
            if source_condition is not None:
                extraction_result = extraction_result.model_copy(
                    update={
                        "action_description": source_condition,
                        "action_source": "keyword_fallback",
                    }
                )

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

        # The model may still select an air-presence condition for a kinetic
        # report. Reconcile that choice deterministically before either sink
        # sees it, then run the normal matcher again with explicit incident
        # evidence. This is the final post-LLM safety boundary.
        if result.matched_condition_id in AIR_VIOLATION_CONDITION_IDS:
            eligibility = evaluate_air_violation_text(
                getattr(message, "raw_text", None)
            )
            if not eligibility.eligible:
                record_air_violation_outcome(
                    message, eligibility, stage="match_incident_action"
                )
                if eligibility.rejected_without_incident or eligibility.held_for_review:
                    # A decided non-event (rules A, B, D) or a row a human must
                    # look at (rule E). Re-running the matcher here would hand
                    # it an invented incident action and push it onward, which
                    # is exactly what the status this just wrote forbids. Save
                    # the match result as-is and stop.
                    self.raw_messages.save_match_result(message, result)
                    return result
                # Only a kinetic report carries enough evidence to infer an
                # incident action.
                incident_action = (
                    condition_fallback_from_text(
                        getattr(message, "raw_text", None)
                    )
                    or "Unclassified / Needs Review"
                )
                extraction_result = extraction_result.model_copy(
                    update={"action_description": incident_action}
                )
                result = self.matching_service.match(
                    extraction_result,
                    cnrs_classification=None,
                )
        # Route air violations before marking matching complete. If routing
        # fails, match_result remains unset and the pipeline can safely retry
        # this message instead of terminalizing it without an AirViolation row.
        if self.air_violations is not None:
            self.air_violations.route_from_match(message, result)
        self.raw_messages.save_match_result(message, result)
        return result
