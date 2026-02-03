"""
Módulo de esquemas de datos.
Gestiona la creación de los esquemas de datos para la base de datos.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    """Esquema base para datos de usuario."""

    name: str
    email: EmailStr


class UserCreate(UserBase):
    """Esquema para la creación de un nuevo usuario."""

    password: str


class UserResponse(UserBase):
    """Esquema de respuesta con datos públicos del usuario."""

    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Esquema para la solicitud de inicio de sesión."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Esquema para el token de autenticación (JWT)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Esquema para la solicitud de refresco de token."""

    refresh_token: str


class VideoBase(BaseModel):
    """Esquema base para datos de video."""

    name: str
    job_id: str
    duration_in_seconds: int
    format: str
    album_id: int


class VideoUpdate(BaseModel):
    """Esquema para la actualización de datos de video."""

    name: Optional[str] = None


class VideoResponse(VideoBase):
    """Esquema de respuesta con datos completos del video."""

    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AlbumBase(BaseModel):
    """Esquema base para datos de álbum."""

    name: str
    description: str


class AlbumCreate(AlbumBase):
    """Esquema para la creación de un nuevo álbum."""

    user_id: int


class AlbumUpdate(BaseModel):
    """Esquema para la actualización de datos de álbum."""

    name: Optional[str] = None
    description: Optional[str] = None


class AlbumResponse(AlbumBase):
    """Esquema de respuesta con datos completos del álbum."""

    id: int
    user_id: int
    created_at: datetime
    videos: List[VideoResponse] = []

    class Config:
        from_attributes = True
