from app.core.text_normalization import normalize_arabic_text
from app.news.interfaces import VillageRepositoryInterface
from app.news.interfaces import VillageMatchingInterface
from app.news.models import Village

# Initial pg_trgm cutoff; tune after reviewing real extraction audit results.
VILLAGE_MATCH_THRESHOLD = 0.35


class VillageMatchingService(VillageMatchingInterface):
    def __init__(self, village_repository: VillageRepositoryInterface) -> None:
        self.village_repository = village_repository

    def match(self, location_text: str) -> Village | None:
        normalized_location = normalize_arabic_text(location_text)
        if not normalized_location:
            return None

        result = self.village_repository.find_best_match_by_normalized_name(
            normalized_location
        )
        if result is None:
            return None

        village, score = result
        if score < VILLAGE_MATCH_THRESHOLD:
            return None
        return village
