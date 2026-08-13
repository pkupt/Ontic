"""AIP / Agent（S5）：把 Ontology 能力暴露给自然语言与 Agent。

两层能力：
1. 工具平面（TOOLS + dispatch_tool）：本体操作的结构化入口，OMCP 与聊天 Agent 共用。
2. 聊天 Agent（chat）：规则规划器为主、LLM 为辅——有 LLM key 时让模型做意图分类，
   否则用关键词规则；最终都下推到同一套本体工具，保证可验证、可控、不越权。

LLM 接入走 SiliconFlow 的 OpenAI 兼容接口（默认关闭，配了 key 才启用），
任意失败都安全回退到规则规划器，绝不让端点崩。
"""
import json
import os
import urllib.request

from . import db
from .ontology import metadata, resolver, actions


# ---- 工具平面（OMCP 与聊天 Agent 共用）----
TOOLS = [
    {
        "name": "list_object_types",
        "description": "列出当前 Ontology 中所有可用的对象类型（业务实体）。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_object_type",
        "description": "查看某个对象类型的字段定义（属性、类型、主键）。",
        "input_schema": {
            "type": "object",
            "properties": {"type_id": {"type": "string"}},
            "required": ["type_id"],
        },
    },
    {
        "name": "query_object_set",
        "description": "按过滤条件查询某对象类型的对象集（下推到数据平面）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_id": {"type": "string"},
                "where": {"type": "object"},
                "limit": {"type": "integer"},
            },
            "required": ["type_id"],
        },
    },
    {
        "name": "execute_action",
        "description": "执行一个动作（create/update/delete 等写操作）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["action_id", "params"],
        },
    },
]


def dispatch_tool(tool: str, args: dict):
    """执行一个本体工具，返回可序列化的结果。所有异常就地转成友好错误。"""
    args = args or {}
    try:
        if tool == "list_object_types":
            return {"object_types": [t["id"] for t in metadata.list_object_types()]}
        if tool == "describe_object_type":
            ot = metadata.get_object_type(args["type_id"])
            if not ot:
                return {"error": f"对象类型不存在: {args['type_id']}"}
            return {
                "id": ot["id"],
                "name": ot.get("name"),
                "primary_key": ot["primary_key"],
                "properties": json.loads(ot["properties"]),
            }
        if tool == "query_object_set":
            where = args.get("where") or None
            limit = int(args.get("limit", 50))
            rows = resolver.query_object_set(
                args["type_id"], {"where": where, "limit": limit, "offset": 0}
            )
            return {"rows": rows, "count": len(rows)}
        if tool == "execute_action":
            detail = actions.execute_action(args["action_id"], args.get("params", {}))
            return {"detail": detail}
        return {"error": f"未知工具: {tool}"}
    except (KeyError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:  # 兜底，避免 Agent 调用把服务打挂
        return {"error": f"工具执行失败: {e}"}


# ---- 规则规划器（无 LLM 时的默认意图识别）----
# 中文别名 → 对象类型 id（仅用于规则兜底，让演示能用中文点名）。
_ALIASES = {
    "客户": "customer", "顾客": "customer", "用户": "customer",
    "产品": "product", "商品": "product", "货品": "product",
    "库存": "low_stock", "低库存": "low_stock",
}

_STATUS_WORDS = {"active": "active", "活跃": "active", "inactive": "inactive", "停用": "inactive"}


def _resolve_type(msg: str, types: list):
    """从消息里解析出命中的对象类型 id（支持英文 id/name 与中文别名）。"""
    low = msg.lower()
    by_id = {t["id"].lower(): t["id"] for t in types}
    for t in types:
        if t["id"].lower() in low or (t.get("name") or "").lower() in low:
            return t["id"]
    for alias, tid in _ALIASES.items():
        if alias in msg and tid in by_id:
            return tid
    return None


def _rule_plan(message: str, types: list):
    msg = message.strip()

    if any(k in msg for k in ("列出", "有哪些", "对象类型", "object type", "list")) and not _resolve_type(msg, types):
        return {"tool": "list_object_types", "args": {}}
    if any(k in msg for k in ("帮助", "help", "能做什么", "你会", "功能", "怎么用")):
        return {"tool": "__help__", "args": {}}

    hit = _resolve_type(msg, types)
    if hit:
        ot = next((t for t in types if t["id"] == hit), None)
        props = {p["key"] for p in json.loads(ot["properties"])} if ot else set()
        where = None
        if "status" in props:
            for w, val in _STATUS_WORDS.items():
                if w in msg:
                    where = {"op": "eq", "field": "status", "value": val}
                    break
        return {"tool": "query_object_set", "args": {"type_id": hit, "where": where, "limit": 50}}
    return {"tool": "__help__", "args": {}}


_HELP = (
    "我是 Ontic 的 AIP Agent。我可以帮你：\n"
    "· 列出所有对象类型（说「列出对象类型」）\n"
    "· 查询某类对象（说「查客户」「看 product 状态为 active 的」）\n"
    "· 描述某对象类型的字段（说「customer 有哪些字段」）\n"
    "· 执行写动作（通过 execute_action 工具，由上层系统调用）"
)


# ---- 可选 LLM 意图分类（SiliconFlow OpenAI 兼容）----
def llm_available() -> bool:
    """是否配置了 LLM（OpenAI 兼容，支持 SiliconFlow/DeepSeek/vLLM/Ollama 等）。"""
    return bool(os.environ.get("ONTIC_LLM_API_KEY") or os.environ.get("SILICONFLOW_API_KEY"))


def llm_config():
    return {
        "base_url": os.environ.get("ONTIC_LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
        "model": os.environ.get("ONTIC_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct"),
    }


def llm_chat(message: str) -> str:
    """纯 LLM 对话（不经过工具），供 Playground / 分析师 LLM 引擎使用。"""
    if not llm_available():
        raise ValueError("未配置 ONTIC_LLM_API_KEY，LLM 引擎不可用（当前为规则规划器）")
    key = os.environ.get("ONTIC_LLM_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
    cfg = llm_config()
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": message}],
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _llm_plan(message: str, types: list):
    key = os.environ.get("ONTIC_LLM_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
    if not key:
        return None
    base = os.environ.get("ONTIC_LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.environ.get("ONTIC_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    system = (
        "你是 Ontic 数据平台的意图分类器。根据用户输入，从下面的工具里选一个最合适"
        "的，并以严格 JSON 返回 {\"tool\": <工具名>, \"args\": <参数对象>}。"
        "只能从工具列表中选择，不要编造。\n工具列表:\n"
        + json.dumps(TOOLS, ensure_ascii=False)
        + "\n当前可用对象类型: " + ", ".join(t["id"] for t in types)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "tool" in parsed:
            return {"tool": parsed["tool"], "args": parsed.get("args", {})}
    except Exception:
        return None
    return None


def chat(message: str, history=None):
    """聊天入口：LLM 优先（若有 key），否则规则；最终都落到 dispatch_tool。"""
    types = metadata.list_object_types()
    plan = _llm_plan(message, types) or _rule_plan(message, types)
    tool, args = plan["tool"], plan.get("args", {})

    if tool == "__help__":
        return {"reply": _HELP, "tool": None, "args": None, "result": None}

    result = dispatch_tool(tool, args)
    reply = _format_result(tool, args, result)
    return {"reply": reply, "tool": tool, "args": args, "result": result}


def _format_result(tool, args, result):
    if isinstance(result, dict) and result.get("error"):
        return f"⚠️ {result['error']}"
    if tool == "list_object_types":
        ts = result.get("object_types", [])
        return "当前 Ontology 包含以下对象类型：\n- " + "\n- ".join(ts) if ts else "暂无对象类型。"
    if tool == "describe_object_type":
        props = result.get("properties", [])
        lines = [f"{p['key']} ({p['type']})" for p in props]
        return f"对象类型 {result.get('id')}（主键 {result.get('primary_key')}）字段：\n- " + "\n- ".join(lines)
    if tool == "query_object_set":
        rows = result.get("rows", [])
        if not rows:
            return f"未查到 {args.get('type_id')} 的匹配对象。"
        cols = list(rows[0].keys())
        head = " | ".join(cols)
        body = "\n".join(" | ".join(str(r.get(c, "")) for c in cols) for r in rows[:20])
        more = f"\n…共 {len(rows)} 行" if len(rows) > 20 else ""
        return f"查询 {args.get('type_id')} 返回 {len(rows)} 行：\n{head}\n{body}{more}"
    if tool == "execute_action":
        return f"已执行动作 {args.get('action_id')}：{json.dumps(result.get('detail'), ensure_ascii=False)}"
    return json.dumps(result, ensure_ascii=False)
