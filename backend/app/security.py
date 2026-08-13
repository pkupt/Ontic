"""认证：密码哈希(PBKDF2, stdlib) + JWT(HS256)。无第三方加密依赖。"""
import hashlib
import secrets
import datetime
import jwt
from . import config


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hashed = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
        return secrets.compare_digest(dk.hex(), hashed)
    except Exception:
        return False


def create_access_token(subject: str) -> str:
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": exp}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM]).get("sub")
    except Exception:
        return None
