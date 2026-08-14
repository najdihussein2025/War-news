from app.dtos.news import SourceListItemDTO
from app.interfaces.repositories import SourceRepositoryInterface


class ListSourcesAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self) -> list[SourceListItemDTO]:
        return self.sources.list_all()
