"""H1 可配置 AIP Chatbot（对齐 chatbot-studio 分区）。

可创建多个自定义 Chatbot：名称/描述 + 指令(instructions) + 工具集白名单 + 参数变量。
运行会话时：参数变量 {key} 用用户输入填充 → 指令 + 消息注入规划器 → 按工具集限制执行。
"""
import json
import datetime

from . import db
from . import aip

_ALL_TOOLS = [t["name"] for t in aip.TOOLS]


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chatbots (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            instructions TEXT,
            tools TEXT,
            params TEXT,
            knowledge TEXT,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chatbot_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chatbot_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def create(c: dict):
    cid = (c.get("id") or "").strip()
    if not cid:
        raise ValueError("Chatbot id 必填")
    tools = c.get("tools") or []
    for t in tools:
        if t not in _ALL_TOOLS:
            raise ValueError(f"未知工具: {t}（可选: {_ALL_TOOLS}）")
    knowledge = c.get("knowledge") or []
    if isinstance(knowledge, str):
        knowledge = [t.strip() for t in knowledge.split(",") if t.strip()]
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO chatbots (id, name, description, instructions, tools, params, knowledge, created) VALUES (?,?,?,?,?,?,?,?)",
        (cid, c.get("name", cid), c.get("description", ""), c.get("instructions", ""),
         json.dumps(tools, ensure_ascii=False),
         json.dumps(c.get("params") or [], ensure_ascii=False),
         json.dumps(knowledge, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": cid}


def list_all():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM chatbots ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get(cid):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM chatbots WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete(cid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM chatbots WHERE id=?", (cid,))
    conn.commit()
    conn.close()


def list_messages(cid: str, limit: int = 50):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT * FROM chatbot_messages WHERE chatbot_id=? ORDER BY id DESC LIMIT ?",
        (cid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def _log_message(cid: str, role: str, content: str):
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO chatbot_messages (chatbot_id, role, content, ts) VALUES (?,?,?,?)",
        (cid, role, content[:2000], _now()),
    )
    conn.commit()
    conn.close()


def chat(cid: str, message: str, param_values: dict = None):
    """运行 Chatbot 会话：参数填充指令 → 规划器（工具集受限）+ 消息持久化。"""
    cb = get(cid)
    if not cb:
        raise ValueError("Chatbot 不存在")
    _log_message(cid, "user", message)
    tools = json.loads(cb["tools"] or "[]")
    params = json.loads(cb["params"] or "[]")
    instructions = cb["instructions"] or ""
    vals = param_values or {}
    # 必填参数校验
    for p in params:
        if p.get("required") and not str(vals.get(p["key"], "")).strip():
            raise ValueError(f"参数 {p.get('label') or p['key']} 必填")
    # 参数变量 {key} → 用户输入值
    for p in params:
        instructions = instructions.replace("{" + p["key"] + "}", str(vals.get(p["key"], "")))
    merged = (instructions + "\n\n" + message).strip() if instructions else message
    # H4 RAG：按知识标签检索相关条目注入提示
    hits = []
    knowledge_tags = json.loads(cb["knowledge"] or "[]")
    if knowledge_tags:
        from . import knowledge as _kb
        hits = _kb.search(message, top_k=2, tags=knowledge_tags)
        if hits:
            ctx = "\n".join(f"- {h['content']}" for h in hits)
            merged = f"参考知识（基于检索上下文）：\n{ctx}\n\n{merged}"
    out = aip.chat(merged, None, allowed_tools=tools or None)
    # RAG 兜底：规则规划器无法识别（无工具可执行）且命中了知识 → 直接以知识作答
    if (out.get("tool") is None or out.get("tool") == "__help__") and hits:
        out["reply"] = "根据知识库：\n" + "\n".join(f"· {h['content']}" for h in hits)
        out["rag"] = True
    out["chatbot"] = cid
    _log_message(cid, "assistant", out.get("reply", ""))
    return out
