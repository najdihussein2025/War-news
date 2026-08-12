from sqlalchemy.orm import Session

from app.actions.news import (
    ExtractIncidentsAction,
    FilterRelevanceAction,
    IngestSourceAction,
)
from app.interfaces.news import (
    ExtractionClassifierInterface,
    RelevanceClassifierInterface,
)


def build_filter_relevance_action(
    db: Session,
    classifier: RelevanceClassifierInterface | None = None,
) -> FilterRelevanceAction:
    from app.repositories.news import (
        ConditionRepository,
        RawMessageRepository,
        VillageRepository,
    )
    from app.services.news.keyword_prefilter_service import KeywordPrefilterService

    if classifier is None:
        raise RuntimeError("No relevance classifier is configured.")

    conditions = ConditionRepository(db)
    villages = VillageRepository(db)
    return FilterRelevanceAction(
        raw_messages=RawMessageRepository(db),
        classifier=classifier,
        keyword_prefilter=KeywordPrefilterService(
            village_repository=villages,
            condition_repository=conditions,
        ),
    )


def build_extract_incidents_action(
    db: Session,
    classifier: ExtractionClassifierInterface | None = None,
) -> ExtractIncidentsAction:
    from app.repositories.news import (
        ConditionRepository,
        IncidentRepository,
        RawMessageRepository,
        VillageRepository,
    )
    from app.services.news.condition_resolution_service import (
        ConditionResolutionService,
    )
    from app.services.news.dedup_matching_service import DedupMatchingService
    from app.services.news.embedding_service import EmbeddingService
    from app.services.news.village_matching_service import VillageMatchingService

    if classifier is None:
        raise RuntimeError("No extraction classifier is configured.")

    raw_messages = RawMessageRepository(db)
    conditions = ConditionRepository(db)
    villages = VillageRepository(db)
    incidents = IncidentRepository(db)
    return ExtractIncidentsAction(
        raw_messages=raw_messages,
        incidents=incidents,
        conditions=conditions,
        classifier=classifier,
        condition_resolver=ConditionResolutionService(),
        village_matcher=VillageMatchingService(village_repository=villages),
        dedup_matcher=DedupMatchingService(incident_repository=incidents),
        embedding_service=EmbeddingService(),
    )


def build_ingest_source_action(db: Session) -> IngestSourceAction:
    from app.repositories.news import SourceRepository

    return IngestSourceAction(sources=SourceRepository(db))
