"""OMCP —— Ontic Model Context Protocol 服务器（S5）。

把 Ontology 能力以 MCP(JSON-RPC 2.0) 方式通过 stdio 暴露给任意 MCP 客户端 / Agent。
这是 Foundry AIP 的「让 Agent 安全读写业务对象」理念的极简开源对应物：
Agent 不直接碰 SQL，而是通过我们定义、受控、可审计的工具来操作本体。

运行： cd backend && python -m app.omcp
协议： 每行一个 JSON-RPC 2.0 请求，stdout 回写 JSON-RPC 响应。
"""
import json
import sys

from . import db
from .ontology import metadata
from . import aip


def _resp(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(message: dict) -> dict:
    method = message.get("method")
    mid = message.get("id")
    params = message.get("params", {}) or {}

    if method == "initialize":
        return _resp(mid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ontic-omcp", "version": "0.1.0"},
        })
    if method == "ping":
        return _resp(mid, {})
    if method == "tools/list":
        return _resp(mid, {
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["input_schema"],
                }
                for t in aip.TOOLS
            ]
        })
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        # 确保元数据已初始化（独立进程运行时）
        try:
            metadata.list_object_types()
        except Exception:
            pass
        result = aip.dispatch_tool(name, arguments)
        return _resp(mid, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": bool(isinstance(result, dict) and result.get("error")),
        })
    return _err(mid, -32601, f"method not found: {method}")


def serve():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(_err(None, -32700, str(e))) + "\n")
            sys.stdout.flush()
            continue
        out = handle(req)
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
