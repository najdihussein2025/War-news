from sqlalchemy.orm import Session

from app.accounts.dtos import (
    LoginDTO,
    LoginResponseDTO,
    UserResponseDTO,
)
from app.accounts.repositories import AuthSessionRepository, LoginThrottleRepository, UserRepository
from app.accounts.services.auth_service import AuthService


def login_account(db: Session, dto: LoginDTO, client_ip: str, device_id: str) -> LoginResponseDTO:
    user, token = AuthService(
        UserRepository(db),
        AuthSessionRepository(db),
        LoginThrottleRepository(db),
    ).login(dto.username, dto.password, client_ip, device_id)
    return LoginResponseDTO(
        access_token=token,
        user=UserResponseDTO.model_validate(user),
        role=user.role.name,
    )
