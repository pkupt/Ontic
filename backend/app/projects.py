"""多项目/空间（Foundry projects 概念）：资源归属分组 + 过滤。

projects 表承载项目；对象类型/应用/管道通过 project_id 归属。
项目不物理隔离数据（共享 DuckDB/SQLite），仅提供资源分组与过滤视图。
"""
import datetime

from . import db


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def create(p: dict):
    pid = (p.get("id") or "").strip()
    if not pid:
        raise ValueError("项目 id 必填")
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO projects (id, name, description, created) VALUES (?,?,?,?)",
        (pid, p.get("name", pid), p.get("description", ""), _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": pid}


def list_all():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["types"] = _count(d["id"], "object_types")
        d["apps"] = _count(d["id"], "apps")
        d["pipelines"] = _count(d["id"], "pipelines")
        out.append(d)
    return out


def _count(project_id, table):
    conn = db.get_metadata_conn()
    if project_id == "default":
        n = conn.execute(f"SELECT count(*) FROM {table} WHERE project_id IS NULL OR project_id='default'").fetchone()[0]
    else:
        n = conn.execute(f"SELECT count(*) FROM {table} WHERE project_id=?", (project_id,)).fetchone()[0]
    conn.close()
    return n


def get(pid):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete(pid):
    if pid == "default":
        raise ValueError("默认空间不可删除")
    conn = db.get_metadata_conn()
    # 资源归回默认空间
    conn.execute("UPDATE object_types SET project_id=NULL WHERE project_id=?", (pid,))
    conn.execute("UPDATE apps SET project_id=NULL WHERE project_id=?", (pid,))
    conn.execute("UPDATE pipelines SET project_id=NULL WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}
