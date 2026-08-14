"""H4 RAG 检索上下文（对齐 chatbot-studio retrieval-context）。

知识库条目（id/content/tags）→ 按查询关键词打分检索 top-k → 注入 Chatbot 提示。
简单实现：无向量库，用关键词共现打分；后续可替换为嵌入检索。
"""
import json
import datetime

from . import db


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_items (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            created TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def add(item: dict):
    kid = (item.get("id") or "").strip()
    content = (item.get("content") or "").strip()
    if not kid or not content:
        raise ValueError("id 与 content 必填")
    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO knowledge_items (id, content, tags, created) VALUES (?,?,?,?)",
        (kid, content, json.dumps(tags, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": kid}


def list_all():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM knowledge_items ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete(kid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM knowledge_items WHERE id=?", (kid,))
    conn.commit()
    conn.close()


def search(query: str, top_k: int = 3, tags: list = None):
    """检索打分：词共现 + 整句匹配 + 中文公共字符重叠。"""
    q = (query or "").lower()
    if not q:
        return []
    words = [w for w in q.replace("，", " ").replace("。", " ").replace("？", " ").split() if len(w) > 1]
    qset = set(q)
    scored = []
    for it in list_all():
        it_tags = json.loads(it["tags"] or "[]")
        if tags and not any(t in it_tags for t in tags):
            continue
        c = it["content"].lower()
        score = sum(c.count(w) for w in words) * 3 + (8 if q in c else 0) + len(qset & set(c))
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:top_k]]
