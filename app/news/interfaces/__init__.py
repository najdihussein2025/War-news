from app.news.interfaces.air_violation_repository_interface import (
    AirViolationRepositoryInterface,
)
from app.news.interfaces.condition_repository_interface import (
    ConditionRepositoryInterface,
)
from app.news.interfaces.condition_resolution_interface import (
    ConditionResolutionInterface,
)
from app.news.interfaces.dedup_matching_interface import DedupMatchingInterface
from app.news.interfaces.embedding_service_interface import EmbeddingServiceInterface
from app.news.interfaces.i_matching_service import MatchingServiceInterface
from app.news.interfaces.incident_repository_interface import IncidentRepositoryInterface
from app.news.interfaces.raw_message_repository_interface import (
    RawMessageRepositoryInterface,
)
from app.news.interfaces.village_matching_interface import VillageMatchingInterface
from app.news.interfaces.village_repository_interface import VillageRepositoryInterface

__all__ = [
    "AirViolationRepositoryInterface",
    "ConditionRepositoryInterface",
    "ConditionResolutionInterface",
    "DedupMatchingInterface",
    "EmbeddingServiceInterface",
    "IncidentRepositoryInterface",
    "MatchingServiceInterface",
    "RawMessageRepositoryInterface",
    "VillageMatchingInterface",
    "VillageRepositoryInterface",
]
