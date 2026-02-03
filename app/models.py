"""
Módulo de modelos de la base de datos.
Gestiona la creación de las tablas en la base de datos.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Video(Base):
    """
    Modelo SQLAlchemy que representa un video procesado.

    Atributos:
        id (int): Identificador único del video.
        name (str): Nombre base del archivo de video.
        created_at (datetime): Fecha y hora de creación.
        job_id (str): Identificador del trabajo de procesamiento asociado.
        duration_in_seconds (int): Duración del video en segundos.
        format (str): Formato del archivo (ej. mp4).
        album_id (int): ID del álbum al que pertenece.
    """

    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    job_id = Column(String, nullable=False)
    duration_in_seconds = Column(Integer, nullable=False)
    format = Column(String, nullable=False)
    album_id = Column(Integer, ForeignKey("albums.id"), nullable=False)

    album = relationship("Album", back_populates="videos")


class User(Base):
    """
    Modelo SQLAlchemy que representa un usuario del sistema.

    Atributos:
        id (int): Identificador único del usuario.
        name (str): Nombre completo del usuario.
        email (str): Correo electrónico único.
        password (str): Hash de la contraseña.
        created_at (datetime): Fecha y hora de registro.
        albums (list[Album]): Relación con los álbumes creados por el usuario.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    albums = relationship(
        "Album", back_populates="user", cascade="all, delete"
    )


class Album(Base):
    """
    Modelo SQLAlchemy que representa un álbum de videos.

    Atributos:
        id (int): Identificador único del álbum.
        name (str): Título del álbum.
        description (str): Descripción del contenido del álbum.
        user_id (int): ID del usuario propietario.
        created_at (datetime): Fecha y hora de creación.
        user (User): Relación con el usuario propietario.
        videos (list[Video]): Relación con los videos contenidos en el álbum.
    """

    __tablename__ = "albums"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="albums")
    videos = relationship(
        "Video", back_populates="album", cascade="all, delete"
    )
