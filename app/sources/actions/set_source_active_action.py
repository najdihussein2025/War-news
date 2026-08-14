from app.sources.actions.get_source_action import SourceNotFoundError
from app.sources.dtos import (
    SourceActiveUpdateData,
    SourceDetailDTO,
)
from app.sources.interfaces import SourceRepositoryInterface


class SetSourceActiveAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self, data: SourceActiveUpdateData) -> SourceDetailDTO:
        source = self.sources.set_active(data.source_id, data.is_active)
        if source is None:
            raise SourceNotFoundError("Source not found.")
        return source
