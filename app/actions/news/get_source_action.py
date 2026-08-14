from app.dtos.news import SourceDetailDTO, SourceLookupData
from app.interfaces.repositories import SourceRepositoryInterface


class SourceNotFoundError(Exception):
    pass


class GetSourceAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self, data: SourceLookupData) -> SourceDetailDTO:
        source = self.sources.get_detail(data.source_id)
        if source is None:
            raise SourceNotFoundError("Source not found.")
        return source
