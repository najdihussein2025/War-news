from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.accounts.models import RoleName


class UserCreateDTO(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    role_id: int


class UserActiveUpdateDTO(BaseModel):
    is_active: bool


class UserUpdateDTO(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1)
    role_id: int
    password: str | None = Field(default=None, min_length=8)


class PasswordChangeDTO(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class RoleResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: RoleName


class UserResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    full_name: str
    role: RoleResponseDTO
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
