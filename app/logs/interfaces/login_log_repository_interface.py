from typing import Protocol
from uuid import UUID

from app.logs.dtos import LoginLogFilterData, LoginLogPageDTO


class LoginLogRepositoryInterface(Protocol):
    def record(
        self,
        *,
        username: str,
        success: bool,
        client_ip: str,
        user_id: UUID | None = None,
        failure_reason: str | None = None,
    ) -> None: ...

    def list_page(self, filters: LoginLogFilterData) -> LoginLogPageDTO: ...
