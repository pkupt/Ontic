"""认证：密码哈希(PBKDF2, stdlib) + JWT(HS256)。无第三方加密依赖。"""
import base64
import hashlib
import secrets
import datetime
import jwt
from . import config


def _derive_key(salt: str) -> bytes:
    """从 ONTIC_SECRET_KEY 派生加密密钥（每盐独立，防彩虹表）。"""
    try:
        s = bytes.fromhex(salt)
    except ValueError:
        s = hashlib.sha256(salt.encode("utf-8")).digest()  # 非 hex 盐（如固定用途盐）
    return hashlib.pbkdf2_hmac("sha256", config.SECRET_KEY.encode("utf-8"), s, 50_000)


def encrypt_secret(plain: str) -> str:
    """生产级对称加密（AES-256-GCM，密钥由 ONTIC_SECRET_KEY 派生，随机 nonce）。
    输出格式 enc2$<b64(nonce+ciphertext+tag)>；解密兼容旧版 enc$（XOR 轻量）。"""
    if not plain:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return _encrypt_xor(plain)  # 降级：未安装 cryptography 时用轻量 XOR
    key = _derive_key("aesgcm")
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), None)
    return "enc2$" + base64.b64encode(nonce + ct).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return token or ""
    if token.startswith("enc2$"):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = _derive_key("aesgcm")
            raw = base64.b64decode(token.split("$", 1)[1])
            return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode("utf-8")
        except Exception:
            return ""
    if token.startswith("enc$"):
        return _decrypt_xor(token)
    return token


def _encrypt_xor(plain: str) -> str:
    salt = secrets.token_hex(8)
    key = _derive_key(salt)
    data = plain.encode("utf-8")
    enc = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return f"enc${salt}${base64.b64encode(enc).decode()}"


def _decrypt_xor(token: str) -> str:
    _, salt, b64 = token.split("$", 2)
    key = _derive_key(salt)
    enc = base64.b64decode(b64)
    dec = bytes(b ^ key[i % len(key)] for i, b in enumerate(enc))
    return dec.decode("utf-8")




def validate_password(pw: str) -> str:
    """生产密码策略：长度>=8 且含字母与数字。返回错误信息（空串=通过）。"""
    if not pw or len(pw) < 8:
        return "密码至少 8 位"
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "密码须同时包含字母与数字"
    return ""

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
