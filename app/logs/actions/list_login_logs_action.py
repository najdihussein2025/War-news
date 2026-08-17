from app.logs.dtos import LoginLogFilterData, LoginLogPageDTO
from app.logs.interfaces import LoginLogRepositoryInterface


class ListLoginLogsAction:
    def __init__(self, login_logs: LoginLogRepositoryInterface) -> None:
        self.login_logs = login_logs

    def execute(self, filters: LoginLogFilterData) -> LoginLogPageDTO:
        return self.login_logs.list_page(filters)
