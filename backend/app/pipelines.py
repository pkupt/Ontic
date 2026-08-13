"""管道与转换框架（M5）：把多个转换步骤编排成管道并顺序执行。

每个管道是一组有序步骤：
  step = { name, sql, target? }
- sql：一条 DuckDB SQL（可引用前面步骤产出的 ont__<target> 表，或连接器/对象类型表）。
- target：若指定，执行后把结果注册为 Ontology 对象类型（自动建表+注册+补齐 CRUD）。

执行顺序即步骤在数组中的顺序（按依赖手工排好；后续可加拓扑排序）。
"""
import json
import datetime

from . import db, ingestion
from . import functions
from .ontology import metadata


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pipeline(pipeline: dict):
    steps = pipeline.get("steps") or []
    if not steps:
        raise ValueError("管道至少需要一个步骤")
    results = []
    snapshots = []
    run_id = None
    dconn = db.get_duckdb()
    try:
        functions.register_functions(dconn)  # 让步骤 SQL 可用 ont_* 函数库
        for i, step in enumerate(steps):
            sql = (step.get("sql") or "").strip()
            if not sql:
                raise ValueError(f"步骤 {i+1} 缺少 sql")
            target = step.get("target")
            if target:
                backing = f"ont__{target}"
                # 时间旅行快照：执行前备份旧版本（12378379 简化版）
                if run_id is None:
                    run_id = _begin_run(pipeline.get("id"))
                snap_table = f"ont__{target}__snap_{run_id}"
                dconn.execute(f'CREATE OR REPLACE TABLE "{snap_table}" AS SELECT * FROM "{backing}"')
                snapshots.append(snap_table)
                dconn.execute(f'CREATE OR REPLACE TABLE "{backing}" AS {sql}')
                res = ingestion._register_from_table(
                    target, backing, f"管道 {pipeline.get('id')} 步骤 {i+1}: {step.get('name','')}"
                )
                results.append({"step": i + 1, "name": step.get("name"), "target": target, "rows": res.get("rows")})
            else:
                dconn.execute(sql)
                results.append({"step": i + 1, "name": step.get("name"), "executed": True})
    except Exception:
        if run_id is not None:
            _finish_run(run_id, "failed")
        raise
    finally:
        dconn.close()
    if run_id is not None:
        _finish_run(run_id, "succeeded", json.dumps(results, ensure_ascii=False))
        for t in snapshots:
            _record_snapshot(pipeline.get("id"), t)
    return {"pipeline": pipeline.get("id"), "steps_run": len(steps), "results": results,
            "run_id": run_id, "snapshots": snapshots}


def _begin_run(pid: str):
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO pipeline_runs (pipeline_id, ts, status) VALUES (?,?,'running')",
                 (pid, _now()))
    rid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    conn.commit()
    conn.close()
    return rid


def _finish_run(run_id, status, detail=None):
    conn = db.get_metadata_conn()
    conn.execute("UPDATE pipeline_runs SET status=?, detail=? WHERE id=?",
                 (status, detail, run_id))
    conn.commit()
    conn.close()


def _record_snapshot(pid, table):
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO pipeline_snapshots (pipeline_id, ts, table_name) VALUES (?,?,?)",
                 (pid, _now(), table))
    conn.commit()
    conn.close()


def list_runs(pid: str):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT id, ts, status, detail FROM pipeline_runs WHERE pipeline_id=? ORDER BY id DESC LIMIT 50",
        (pid,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["detail"] = json.loads(d["detail"]) if d["detail"] else None
        except Exception:
            pass
        out.append(d)
    return out


def list_snapshots(pid: str):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT id, ts, table_name FROM pipeline_snapshots WHERE pipeline_id=? ORDER BY id DESC LIMIT 50",
        (pid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def restore_snapshot(pid: str, snap_id: int):
    """回滚：把某次快照（ont__x__snap_<id>）整表恢复到目标表 ont__x。"""
    conn = db.get_metadata_conn()
    row = conn.execute(
        "SELECT table_name FROM pipeline_snapshots WHERE id=? AND pipeline_id=?", (snap_id, pid)
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("快照不存在")
    snap_table = row["table_name"]
    if "__snap_" not in snap_table:
        raise ValueError("快照表名非法")
    target = snap_table.rsplit("__snap_", 1)[0]
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'CREATE OR REPLACE TABLE "{target}" AS SELECT * FROM "{snap_table}"')
    finally:
        dconn.close()
    metadata.log_activity("pipeline", f"从快照 #{snap_id} 恢复 {target}（管道 {pid}）")
    return {"restored": target, "from_snapshot": snap_id}
