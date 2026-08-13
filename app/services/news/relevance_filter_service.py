from app.dtos.news import (
    ClassificationResultDTO,
    ClassificationVerdict,
    RelevanceClassificationResult,
    RelevancePolicyResult,
    RelevancePolicyVerdict,
)
from app.models.news import MessageStatus


def policy_for_result(result: ClassificationResultDTO) -> RelevancePolicyResult:
    if result.verdict == ClassificationVerdict.not_relevant:
        return RelevancePolicyResult(
            verdict=RelevancePolicyVerdict.reject,
            status=MessageStatus.rejected.value,
            needs_review=False,
        )

    if result.verdict == ClassificationVerdict.relevant:
        return RelevancePolicyResult(
            verdict=RelevancePolicyVerdict.proceed,
            status=MessageStatus.parsed.value,
            needs_review=False,
        )

    return RelevancePolicyResult(
        verdict=RelevancePolicyVerdict.uncertain,
        status=MessageStatus.rejected.value,
        needs_review=True,
    )


def status_for_result(result: RelevanceClassificationResult) -> MessageStatus:
    return MessageStatus(policy_for_result(result).status)
