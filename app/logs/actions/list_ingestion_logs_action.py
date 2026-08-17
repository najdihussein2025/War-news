from app.logs.dtos import IngestionLogFilterData, IngestionLogPageDTO
from app.logs.interfaces import IngestionLogRepositoryInterface


class ListIngestionLogsAction:
    def __init__(self, logs: IngestionLogRepositoryInterface) -> None:
        self.logs = logs

    def execute(self, filters: IngestionLogFilterData) -> IngestionLogPageDTO:
        return self.logs.list_page(filters)
