from app.interfaces.news.condition_repository_interface import (
    ConditionRepositoryInterface,
)
from app.interfaces.news.condition_resolution_interface import (
    ConditionResolutionInterface,
)
from app.interfaces.news.dedup_matching_interface import DedupMatchingInterface
from app.interfaces.news.embedding_service_interface import EmbeddingServiceInterface
from app.interfaces.news.extraction_classifier_interface import (
    ExtractionClassifierInterface,
)
from app.interfaces.news.incident_repository_interface import (
    IncidentRepositoryInterface,
)
from app.interfaces.news.raw_message_repository_interface import (
    RawMessageRepositoryInterface,
)
from app.interfaces.news.relevance_classifier_interface import (
    RelevanceClassifierInterface,
)
from app.interfaces.news.source_repository_interface import SourceRepositoryInterface
from app.interfaces.news.keyword_prefilter_interface import KeywordPrefilterInterface
from app.interfaces.news.village_matching_interface import VillageMatchingInterface
from app.interfaces.news.village_repository_interface import VillageRepositoryInterface

__all__ = [
    "ConditionRepositoryInterface",
    "ConditionResolutionInterface",
    "DedupMatchingInterface",
    "EmbeddingServiceInterface",
    "ExtractionClassifierInterface",
    "IncidentRepositoryInterface",
    "KeywordPrefilterInterface",
    "RawMessageRepositoryInterface",
    "RelevanceClassifierInterface",
    "SourceRepositoryInterface",
    "VillageMatchingInterface",
    "VillageRepositoryInterface",
]
