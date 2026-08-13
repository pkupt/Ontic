"""M12 开发者控制台：API 令牌管理。

生成持久化的 API Token（明文 UUID），在 Authorization 头里与 JWT 等价可用；
支持列出、撤销。供开发者/CI/外部应用调用 Ontic REST API 使用。
"""
import uuid
import datetime

from . import db


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def create_token(username: str, label: str = ""):
    token = uuid.uuid4().hex
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO tokens (token, username, label, created, revoked) VALUES (?,?,?,?,0)",
        (token, username, label or "", _now()),
    )
    conn.commit()
    conn.close()
    return {"token": token, "username": username, "label": label or ""}


def list_tokens():
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT id, token, username, label, created, revoked FROM tokens ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_token(token_id: int):
    conn = db.get_metadata_conn()
    conn.execute("UPDATE tokens SET revoked=1 WHERE id=?", (token_id,))
    conn.commit()
    conn.close()


def verify_token(token: str):
    """token 有效则返回用户名，否则 None。"""
    conn = db.get_metadata_conn()
    row = conn.execute(
        "SELECT username FROM tokens WHERE token=? AND revoked=0", (token,)
    ).fetchone()
    conn.close()
    return row["username"] if row else None
