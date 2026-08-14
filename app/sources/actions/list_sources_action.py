from app.sources.dtos import SourceListItemDTO
from app.sources.interfaces import SourceRepositoryInterface


class ListSourcesAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self) -> list[SourceListItemDTO]:
        return self.sources.list_all()
