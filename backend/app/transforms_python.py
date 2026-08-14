"""D1 Python Transforms（对齐 transforms-python 分区，零额外依赖）。

在管道中执行用户自定义 Python 函数（transform(rows) → rows）：
  - 从输入表读取全部行（dict 列表）
  - 执行用户代码中定义的 transform 函数，允许增删改字段
  - 写回输出表（按首行自动推断列类型），可选注册为对象类型

不依赖 pandas/numpy —— 纯 Python 逐行/逐批变换，适合小型数据集与原型。
"""
import re
import math
import json
import datetime

from . import db
from . import ingestion

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# ---- 受限执行沙箱：移除危险 builtins，仅注入安全模块 ----
# 注意：纯 Python 沙箱无法做到 100% 安全，生产环境应进一步容器化隔离。
_DANGEROUS = {
    "exec", "eval", "compile", "open", "input", "__import__",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit", "help", "memoryview", "classmethod",
}
_builtins_dict = getattr(__builtins__, "__dict__", __builtins__)
_SAFE_BUILTINS = {k: v for k, v in _builtins_dict.items() if k not in _DANGEROUS}
_SAFE_GLOBALS = {
    "__builtins__": _SAFE_BUILTINS,
    "math": math, "json": json, "re": re, "datetime": datetime,
    "round": round, "len": len, "range": range, "str": str, "int": int,
    "float": float, "bool": bool, "list": list, "dict": dict, "set": set,
    "tuple": tuple, "sorted": sorted, "enumerate": enumerate, "zip": zip,
    "abs": abs, "min": min, "max": max, "sum": sum, "map": map, "filter": filter,
    "any": any, "all": all, "isinstance": isinstance, "print": print,
}


def _sandbox_exec(code: str):
    """在受限 namespace 中执行用户代码，返回 transform 函数。"""
    ns = dict(_SAFE_GLOBALS)
    exec(compile(code, "<transform>", "exec"), ns)  # noqa: S102 沙箱已限制 builtins
    fn = ns.get("transform")
    if not callable(fn):
        raise ValueError("代码未定义可调用的 transform 函数")
    return fn


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS python_transforms (
            name TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            description TEXT,
            created TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def register(name: str, code: str, description: str = ""):
    if not _NAME_RE.match(name):
        raise ValueError("名称仅允许字母/数字/下划线，且以字母或下划线开头")
    if "def transform" not in code:
        raise ValueError("代码必须定义 def transform(rows)")
    compile(code, "<transform>", "exec")  # 语法校验
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO python_transforms (name, code, description, created) VALUES (?,?,?,?)",
        (name, code, description or "", _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "name": name}


def list_transforms():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT name, description, created FROM python_transforms ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_transform(name: str):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM python_transforms WHERE name=?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_transform(name: str):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM python_transforms WHERE name=?", (name,))
    conn.commit()
    conn.close()


def _infer_type(v):
    if isinstance(v, bool):
        return "BOOLEAN"
    if isinstance(v, int):
        return "INTEGER"
    if isinstance(v, float):
        return "DOUBLE"
    return "VARCHAR"


def run_transform(name: str, input_table: str, output_table: str, object_type: str = ""):
    tf = get_transform(name)
    if not tf:
        raise ValueError(f"Python 转换不存在: {name}")
    fn = _sandbox_exec(tf["code"])

    dconn = db.get_duckdb()
    try:
        cur = dconn.execute(f'SELECT * FROM "{input_table}"')
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        out = fn(rows)
        if out is None:
            out = []
        if out and not isinstance(out[0], dict):
            raise ValueError("transform 必须返回 dict 行列表")
    finally:
        dconn.close()

    if not out:
        # 空输出：建表（仅主键占位列）并直接返回
        dconn = db.get_duckdb()
        try:
            dconn.execute(f'CREATE OR REPLACE TABLE "{output_table}" (id INTEGER)')
        finally:
            dconn.close()
        if object_type:
            ingestion._register_from_table(object_type, output_table, f"Python 转换 {name}（空输出）")
        return {"rows": 0, "columns": ["id"]}

    new_cols = list(out[0].keys())
    col_defs = ", ".join(f'"{c}" {_infer_type(out[0][c])}' for c in new_cols)
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'CREATE OR REPLACE TABLE "{output_table}" ({col_defs})')
        dconn.executemany(
            f'INSERT INTO "{output_table}" ({",".join(f'"{c}"' for c in new_cols)}) VALUES ({",".join(["?"]*len(new_cols))})',
            [[r.get(c) for c in new_cols] for r in out],
        )
    finally:
        dconn.close()
    if object_type:
        ingestion._register_from_table(object_type, output_table, f"Python 转换 {name}")
    return {"rows": len(out), "columns": new_cols}
