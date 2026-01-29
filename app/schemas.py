from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    name: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class MediaBase(BaseModel):
    name: str
    path: str
    format: str
    type: str
    job_id: Optional[str] = None
    album_id: Optional[int] = None


class MediaResponse(MediaBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AlbumBase(BaseModel):
    name: str
    description: Optional[str] = None


class AlbumCreate(AlbumBase):
    user_id: int


class AlbumUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class AlbumResponse(AlbumBase):
    id: int
    user_id: int
    created_at: datetime
    media: List[MediaResponse] = []

    class Config:
        from_attributes = True
