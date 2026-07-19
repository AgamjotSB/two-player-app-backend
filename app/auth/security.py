from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt

from app.config import Config


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")  # store as str in the DB


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=Config.jwt_expire_minutes),
    }

    return jwt.encode(payload, Config.jwt_secret, algorithm=Config.jwt_algorithm)


def decode_access_token(token: str) -> UUID | None:
    try:
        payload = jwt.decode(
            token, Config.jwt_secret, algorithms=[Config.jwt_algorithm]
        )
        return UUID(payload["sub"])

    except jwt.InvalidTokenError, KeyError, ValueError:
        return None
