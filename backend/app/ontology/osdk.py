"""OSDK 代码生成：从 Ontology 元数据生成类型安全的客户端（Python / TypeScript）。

对应 Foundry 的 OSDK —— 让应用和 Agent 用强类型 API 读写业务对象，而不是手写 HTTP。
"""
import json
from .. import db


def _collect():
    conn = db.get_metadata_conn()
    ots = conn.execute("SELECT * FROM object_types").fetchall()
    acts = conn.execute("SELECT * FROM actions").fetchall()
    conn.close()
    return [dict(o) for o in ots], [dict(a) for a in acts]


def generate_python() -> str:
    ots, acts = _collect()
    lines = [
        '"""自动生成的 Ontic OSDK (Python)。请勿手改，由 /api/ontology/osdk/python 生成。""",',
        "from typing import Any, Optional",
        "import requests",
        "",
        "",
        "class Client:",
        '    def __init__(self, base_url: str, token: str):',
        "        self.base = base_url.rstrip('/')",
        '        self.session = requests.Session()',
        '        self.session.headers.update({"Authorization": f"Bearer {token}"})',
        "",
        "    def query(self, object_type: str, **q) -> list[dict]:",
        '        r = self.session.post(f"{self.base}/api/ontology/object-types/{object_type}/query", json=q)',
        "        r.raise_for_status()",
        "        return r.json()['rows']",
        "",
        "    def run_action(self, action_id: str, params: dict) -> dict:",
        '        r = self.session.post(f"{self.base}/api/ontology/actions/{action_id}/execute", json={"params": params})',
        "        r.raise_for_status()",
        "        return r.json()['detail']",
        "",
    ]
    for ot in ots:
        props = json.loads(ot["properties"])
        cls = "".join(p.capitalize() for p in ot["id"].split("_"))
        lines.append(f"class {cls}:")
        lines.append(f'    TYPE = "{ot["id"]}"')
        fields = ", ".join(f"{p['key']}: Any = None" for p in props)
        lines.append(f"    def __init__(self, {fields}):")
        for p in props:
            lines.append(f"        self.{p['key']} = {p['key']}")
        lines.append("")
    return "\n".join(lines)


def generate_typescript() -> str:
    ots, acts = _collect()
    lines = [
        '// 自动生成的 Ontic OSDK (TypeScript)。请勿手改，由 /api/ontology/osdk/typescript 生成。',
        "export interface QueryRequest {",
        "  where?: any; select?: string[]; orderBy?: any; limit?: number; offset?: number;",
        "}",
        "",
        "export class OnticClient {",
        "  constructor(private baseUrl: string, private token: string) {}",
        "  private async post(path: string, body: any): Promise<any> {",
        "    const r = await fetch(this.baseUrl + path, {",
        "      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.token}` }, body: JSON.stringify(body) });",
        "    if (!r.ok) throw new Error(await r.text());",
        "    return r.json();",
        "  }",
        "  async query(objectType: string, q: QueryRequest): Promise<any[]> {",
        "    const r = await this.post(`/api/ontology/object-types/${objectType}/query`, q); return r.rows;",
        "  }",
        "  async runAction(actionId: string, params: Record<string, any>): Promise<any> {",
        "    const r = await this.post(`/api/ontology/actions/${actionId}/execute`, { params }); return r.detail;",
        "  }",
        "}",
        "",
    ]
    for ot in ots:
        props = json.loads(ot["properties"])
        cls = "".join(p.capitalize() for p in ot["id"].split("_"))
        field_decls = ";\n  ".join(f"{p['key']}: {_ts_type(p['type'])}" for p in props)
        lines.append(f"export interface {cls} {{")
        lines.append(f"  {field_decls}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _ts_type(t: str) -> str:
    return {
        "string": "string",
        "integer": "number",
        "double": "number",
        "boolean": "boolean",
    }.get(t, "any")
