from pydantic import BaseModel, Field

from app.dtos.user import UserResponseDTO
from app.models.accounts import RoleName


class LoginDTO(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponseDTO(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponseDTO
    role: RoleName


class SessionResponseDTO(BaseModel):
    user: UserResponseDTO
    role: RoleName
