from sqlalchemy.orm import Session

from app.llm.actions import (
    ExtractIncidentsAction,
    FilterRelevanceAction,
)
from app.news.actions import MatchIncidentAction
from app.sources.actions import IngestSourceAction
from app.llm.interfaces import (
    ExtractionClassifierInterface,
    RelevanceClassifierInterface,
)


def _build_local_llm_relevance_classifier() -> RelevanceClassifierInterface:
    from app.core.config import settings
    from app.core.ollama_client import OllamaChatClient
    from app.llm.services.local_llm_relevance_classifier import (
        LocalLLMRelevanceClassifier,
    )

    return LocalLLMRelevanceClassifier(
        OllamaChatClient(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            model=settings.relevance_ollama_model,
            timeout_seconds=settings.relevance_llm_timeout_seconds,
        ),
        max_retries=settings.relevance_classifier_max_retries,
        retry_backoff_seconds=settings.relevance_classifier_retry_backoff_seconds,
    )


def build_relevance_classifier() -> RelevanceClassifierInterface:
    from app.core.config import settings
    from app.llm.services.cnrs_relevance_classifier import (
        CNRS_PROVIDED_BACKEND,
        CnrsProvidedRelevanceClassifier,
    )

    backend = settings.relevance_classifier_backend.lower()
    if backend == "local_llm":
        return _build_local_llm_relevance_classifier()

    if backend == CNRS_PROVIDED_BACKEND:
        return CnrsProvidedRelevanceClassifier(
            fallback=_build_local_llm_relevance_classifier(),
        )

    if backend == "gemini":
        raise RuntimeError(
            "RELEVANCE_CLASSIFIER_BACKEND=gemini was requested, but no Gemini "
            "classifier implementation is present in this checkout."
        )

    raise RuntimeError(
        "Unsupported RELEVANCE_CLASSIFIER_BACKEND="
        f"{settings.relevance_classifier_backend!r}. "
        "Expected 'local_llm', 'cnrs_provided', or 'gemini'."
    )


def build_filter_relevance_action(
    db: Session,
    classifier: RelevanceClassifierInterface | None = None,
    reviewer_classifier: RelevanceClassifierInterface | None = None,
) -> FilterRelevanceAction:
    from app.core.config import settings
    from app.news.repositories import (
        ConditionRepository,
        RawMessageRepository,
        VillageRepository,
    )
    from app.llm.services.keyword_prefilter_service import KeywordPrefilterService

    if classifier is None:
        classifier = build_relevance_classifier()

    conditions = ConditionRepository(db)
    villages = VillageRepository(db)
    return FilterRelevanceAction(
        raw_messages=RawMessageRepository(db),
        classifier=classifier,
        keyword_prefilter=KeywordPrefilterService(
            village_repository=villages,
            condition_repository=conditions,
        ),
        reviewer_classifier=reviewer_classifier,
        relevance_batch_size=settings.relevance_llm_batch_size,
    )


def build_extraction_classifier() -> ExtractionClassifierInterface:
    from app.core.config import settings
    from app.core.ollama_client import OllamaChatClient
    from app.llm.services.ollama_extraction_service import OllamaExtractionService
    from app.llm.services.cnrs_extraction_fallback import CnrsExtractionFallback

    return CnrsExtractionFallback(OllamaExtractionService(
        OllamaChatClient(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            model=settings.extraction_ollama_model,
            timeout_seconds=settings.extraction_llm_timeout_seconds,
            max_request_retries=settings.extraction_llm_request_retries,
            retry_backoff_seconds=settings.extraction_llm_retry_backoff_seconds,
        )
    ))


def build_extract_incidents_action(
    db: Session,
    classifier: ExtractionClassifierInterface | None = None,
) -> ExtractIncidentsAction:
    from app.news.repositories import RawMessageRepository

    if classifier is None:
        classifier = build_extraction_classifier()

    return ExtractIncidentsAction(
        raw_messages=RawMessageRepository(db),
        classifier=classifier,
    )


def build_ingest_source_action(db: Session) -> IngestSourceAction:
    from app.sources.repositories import SourceRepository

    return IngestSourceAction(sources=SourceRepository(db))


def build_match_incident_action(db: Session) -> MatchIncidentAction:
    from app.news.repositories import (
        AirViolationRepository,
        ConditionRepository,
        RawMessageRepository,
        VillageRepository,
    )
    from app.news.services.matching_service import MatchingService

    return MatchIncidentAction(
        raw_messages=RawMessageRepository(db),
        matching_service=MatchingService(
            village_repository=VillageRepository(db),
            condition_repository=ConditionRepository(db),
        ),
        air_violations=AirViolationRepository(db),
    )
