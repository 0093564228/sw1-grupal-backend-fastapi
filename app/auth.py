"""
Módulo de autenticación.
Gestiona la autenticación de usuarios.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User

# Configuración
SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY", "your-super-secret-key-change-in-production"
)
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)
REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# JWT Bearer scheme
security = HTTPBearer()


def get_db():
    """
    Obtiene una sesión de base de datos.

    Returns:
        Session: Sesión de base de datos.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña en texto plano coincide con su hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Genera un hash seguro para la contraseña dada."""
    return pwd_context.hash(password)


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Crea un token de acceso JWT.

    Args:
        data (dict): Datos a incluir en el payload del token.
        expires_delta (timedelta, optional): Tiempo de expiración personalizado.

    Returns:
        str: Token JWT codificado.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Crea un token de refresco JWT con mayor duración.

    Args:
        data (dict): Datos a incluir en el payload.

    Returns:
        str: Token JWT de refresco codificado.
    """
    data_copy = (
        data.copy()
    )  # Evitar modificar el diccionario original si se reutiliza fuera
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un token JWT.

    Args:
        token (str): Token JWT a decodificar.

    Returns:
        dict: Payload del token si es válido.

    Raises:
        HTTPException: Si el token es inválido o ha expirado.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as ex:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from ex


def authenticate_user(
    db: Session, email: str, password: str
) -> Optional[User]:
    """
    Autentica a un usuario verificando su email y contraseña.

    Args:
        db (Session): Sesión de base de datos.
        email (str): Correo del usuario.
        password (str): Contraseña en texto plano.

    Returns:
        Optional[User]: Objeto User si las credenciales son válidas, None en caso contrario.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependencia de FastAPI para obtener el usuario autenticado actual desde el token.

    Args:
        credentials (HTTPAuthorizationCredentials): Credenciales Bearer extraídas del header.
        db (Session): Sesión de base de datos.

    Returns:
        User: El usuario autenticado.

    Raises:
        HTTPException: Si el token es inválido, ha expirado o el usuario no existe.
    """
    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError) as ex:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from ex
    user = db.query(User).filter(User.id == user_id_int).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
