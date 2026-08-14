"""数据版本控制：检查点（Checkpoints）+ 分支（Branches）。

对齐 Foundry 数据能力原型：
  - 检查点（checkpoints 6 篇 / 12378379 时间旅行）：对对象类型手动打点，
    可列表、恢复、与当前数据对比差异。
  - 全局分支（global-branching 简化）：基于检查点创建命名分支副本，
    可查看、可应用（用分支覆盖主表）、可删除。

存储模型：
  - 检查点表：ont__<type>__ckpt_<id>
  - 分支表：  ont__<type>__branch_<name>
"""
import re
import datetime

from . import db
from .ontology import metadata

_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _type_table(object_type: str):
    ot = metadata.get_object_type(object_type)
    if not ot:
        raise ValueError("对象类型不存在")
    return ot


def _copy_table(dconn, src: str, dst: str):
    dconn.execute(f'CREATE OR REPLACE TABLE "{dst}" AS SELECT * FROM "{src}"')


# ---- 检查点 ----
def create_checkpoint(object_type: str, label: str = ""):
    ot = _type_table(object_type)
    conn = db.get_metadata_conn()
    cid = conn.execute("SELECT COALESCE(MAX(id),0)+1 AS i FROM checkpoints").fetchone()["i"]
    conn.close()
    table = f"ont__{object_type}__ckpt_{cid}"
    dconn = db.get_duckdb()
    try:
        _copy_table(dconn, ot["backing_table"], table)
    finally:
        dconn.close()
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO checkpoints (object_type, label, table_name, ts) VALUES (?,?,?,?)",
                 (object_type, label or f"检查点 {cid}", table, _now()))
    conn.commit()
    conn.close()
    return {"checkpoint": cid, "object_type": object_type, "table_name": table}


def list_checkpoints(object_type: str = ""):
    conn = db.get_metadata_conn()
    sql = "SELECT id, object_type, label, table_name, ts FROM checkpoints"
    params = ()
    if object_type:
        sql += " WHERE object_type=?"
        params = (object_type,)
    rows = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def restore_checkpoint(cid: int):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM checkpoints WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("检查点不存在")
    cp = dict(row)
    target = metadata.get_object_type(cp["object_type"])["backing_table"]
    dconn = db.get_duckdb()
    try:
        _copy_table(dconn, cp["table_name"], target)
    finally:
        dconn.close()
    metadata.log_activity("version", f"恢复检查点 #{cid} → {target}")
    return {"restored": target, "checkpoint": cid}


def checkpoint_diff(cid: int):
    """差异（简化）：检查点 vs 当前表 —— 行数 + 逐列非空计数。"""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM checkpoints WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("检查点不存在")
    cp = dict(row)
    target = metadata.get_object_type(cp["object_type"])["backing_table"]
    dconn = db.get_duckdb()
    try:
        n_old = int(dconn.execute(f'SELECT COUNT(*) FROM "{cp["table_name"]}"').fetchone()[0])
        n_new = int(dconn.execute(f'SELECT COUNT(*) FROM "{target}"').fetchone()[0])
        cols = [d[0] for d in dconn.execute(f'SELECT * FROM "{cp["table_name"]}" LIMIT 1').description] if n_old else []
        col_stats = []
        for c in cols[:12]:
            try:
                a = int(dconn.execute(f'SELECT COUNT("{c}") FROM "{cp["table_name"]}"').fetchone()[0])
                b = int(dconn.execute(f'SELECT COUNT("{c}") FROM "{target}"').fetchone()[0])
            except Exception:
                continue
            col_stats.append({"column": c, "old_nonnull": a, "new_nonnull": b,
                              "changed": a != b or n_old != n_new})
    finally:
        dconn.close()
    return {"checkpoint": cid, "object_type": cp["object_type"], "rows_old": n_old, "rows_new": n_new,
            "rows_diff": n_new - n_old, "columns": col_stats}


def delete_checkpoint(cid: int):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT table_name FROM checkpoints WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("检查点不存在")
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'DROP TABLE IF EXISTS "{row["table_name"]}"')
    finally:
        dconn.close()
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM checkpoints WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---- 分支 ----
def create_branch(object_type: str, name: str, base_ckpt: int = None):
    if not _NAME_RE.match(name):
        raise ValueError("分支名仅允许字母/数字/下划线")
    ot = _type_table(object_type)
    table = f"ont__{object_type}__branch_{name}"
    conn = db.get_metadata_conn()
    if conn.execute("SELECT 1 FROM branches WHERE table_name=?", (table,)).fetchone():
        conn.close()
        raise ValueError(f"分支已存在: {name}")
    conn.close()
    src = None
    if base_ckpt:
        conn = db.get_metadata_conn()
        row = conn.execute("SELECT table_name FROM checkpoints WHERE id=? AND object_type=?",
                           (base_ckpt, object_type)).fetchone()
        conn.close()
        if not row:
            raise ValueError("基础检查点不存在")
        src = row["table_name"]
    dconn = db.get_duckdb()
    try:
        _copy_table(dconn, src or ot["backing_table"], table)
    finally:
        dconn.close()
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO branches (object_type, name, table_name, base_ckpt, ts) VALUES (?,?,?,?,?)",
                 (object_type, name, table, base_ckpt, _now()))
    conn.commit()
    conn.close()
    return {"branch": name, "object_type": object_type, "table_name": table}


def list_branches(object_type: str = ""):
    conn = db.get_metadata_conn()
    sql = "SELECT id, object_type, name, table_name, base_ckpt, ts FROM branches"
    params = ()
    if object_type:
        sql += " WHERE object_type=?"
        params = (object_type,)
    rows = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def apply_branch(bid: int):
    """用分支数据覆盖主表（回切分支）。"""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("分支不存在")
    br = dict(row)
    target = metadata.get_object_type(br["object_type"])["backing_table"]
    dconn = db.get_duckdb()
    try:
        _copy_table(dconn, br["table_name"], target)
    finally:
        dconn.close()
    metadata.log_activity("version", f"应用分支 {br['object_type']}/{br['name']} → 主表")
    return {"applied": target, "branch": br["name"]}


def delete_branch(bid: int):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT table_name FROM branches WHERE id=?", (bid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("分支不存在")
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'DROP TABLE IF EXISTS "{row["table_name"]}"')
    finally:
        dconn.close()
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM branches WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    return {"ok": True}


def get_branch(bid: int):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_branch_protection(bid: int, protect: bool):
    br = get_branch(bid)
    if not br:
        raise ValueError("分支不存在")
    conn = db.get_metadata_conn()
    conn.execute("UPDATE branches SET protected=? WHERE id=?", (1 if protect else 0, bid))
    conn.commit()
    conn.close()
    return {"ok": True, "branch": br["name"], "protected": bool(protect)}
