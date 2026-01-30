from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base



class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    job_id = Column(String, nullable=True)
    duration = Column(Integer, nullable=True)
    type = Column(String, nullable=False)
    album_id = Column(Integer, ForeignKey("albums.id"), nullable=False)
    thumbnail_id = Column(Integer, ForeignKey("media.id"), nullable=True)

    album = relationship("Album", back_populates="videos")
    media = relationship("Media", back_populates="video", foreign_keys="[Media.video_id]", cascade="all, delete")
    thumbnail = relationship("Media", foreign_keys=[thumbnail_id], post_update=True)


class Media(Base):
    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    format = Column(String, nullable=False)
    type = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)

    video = relationship("Video", back_populates="media", foreign_keys=[video_id])


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    albums = relationship("Album", back_populates="user", cascade="all, delete")


class Album(Base):
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="albums")
    videos = relationship("Video", back_populates="album", cascade="all, delete")

