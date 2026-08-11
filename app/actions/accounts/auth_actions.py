from sqlalchemy.orm import Session

from app.dtos import LoginDTO, LoginResponseDTO, UserResponseDTO
from app.repositories import AuthSessionRepository, UserRepository
from app.services.auth_service import AuthService


def login_account(db: Session, dto: LoginDTO) -> LoginResponseDTO:
    user, token = AuthService(UserRepository(db), AuthSessionRepository(db)).login(dto.username, dto.password)
    return LoginResponseDTO(
        access_token=token,
        user=UserResponseDTO.model_validate(user),
        role=user.role.name,
    )
