"""元数据仓：用户、对象类型、链接、动作的定义与初始化。

这是 Ontology 层的"大脑"——所有对象/链接/动作的结构化定义都存这里（SQLite），
而真实数据落在 DuckDB 的 backing table 里。元数据定义对象如何映射到数据平面。
"""
import json
import datetime
from .. import db, security, config


def init_metadata():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin'
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS object_types (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            backing_table TEXT NOT NULL,
            primary_key TEXT NOT NULL,
            properties TEXT NOT NULL,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS links (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            join_table TEXT,
            source_fk TEXT,
            target_fk TEXT,
            properties TEXT
        );
        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            object_type TEXT NOT NULL,
            operation TEXT NOT NULL,
            parameters TEXT NOT NULL,
            needs_approval INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(object_type) REFERENCES object_types(id)
        );
        CREATE TABLE IF NOT EXISTS grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            object_type TEXT NOT NULL,
            level TEXT NOT NULL,
            UNIQUE(username, object_type)
        );
        CREATE TABLE IF NOT EXISTS pipelines (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            steps TEXT NOT NULL,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            model TEXT NOT NULL,
            metric TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            success BOOLEAN NOT NULL DEFAULT 1,
            source TEXT,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS eval_suites (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suite_id TEXT NOT NULL,
            name TEXT NOT NULL,
            input TEXT NOT NULL,
            expected TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suite_id TEXT NOT NULL,
            run_ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            output TEXT,
            pass BOOLEAN NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            type TEXT NOT NULL,
            object_type TEXT NOT NULL,
            config TEXT NOT NULL,
            created TEXT NOT NULL,
            updated TEXT NOT NULL,
            project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS app_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS security_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            object_type TEXT NOT NULL,
            summary TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            requester TEXT NOT NULL,
            object_type TEXT NOT NULL,
            action_id TEXT NOT NULL,
            params TEXT NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer TEXT
        );
        CREATE TABLE IF NOT EXISTS retention (
            object_type TEXT PRIMARY KEY,
            days INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS type_markings (
            object_type TEXT NOT NULL,
            marking TEXT NOT NULL,
            PRIMARY KEY(object_type, marking)
        );
        CREATE TABLE IF NOT EXISTS model_objectives (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            model_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            note TEXT,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monitors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            object_type TEXT NOT NULL,
            metric TEXT NOT NULL DEFAULT 'count',
            op TEXT NOT NULL DEFAULT 'gt',
            threshold REAL NOT NULL DEFAULT 100,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            action_id TEXT,
            action_params TEXT
        );
        CREATE TABLE IF NOT EXISTS automation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail TEXT,
            ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            label TEXT,
            created TEXT NOT NULL,
            revoked BOOLEAN NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS endpoints (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            method TEXT NOT NULL,
            sql TEXT NOT NULL,
            description TEXT,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS pipeline_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            table_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            label TEXT,
            table_name TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            base_ckpt INTEGER,
            ts TEXT NOT NULL,
            protected INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL,
            created TEXT NOT NULL,
            updated TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS thread_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS installed_packages (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            installed_at TEXT NOT NULL
        );
        """
    )
    cur = conn.execute("SELECT id FROM users WHERE username=?", (config.ADMIN_USER,))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            (config.ADMIN_USER, security.hash_password(config.ADMIN_PASSWORD), "admin"),
        )
    # 存量库迁移：actions 表补 needs_approval 列
    try:
        conn.execute("ALTER TABLE actions ADD COLUMN needs_approval INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE branches ADD COLUMN protected INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    # 存量库迁移：monitors 表补 action_id 列（E1 事件触发器）
    try:
        conn.execute("ALTER TABLE monitors ADD COLUMN action_id TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE monitors ADD COLUMN action_params TEXT")
    except Exception:
        pass
    # 存量库迁移：chatbots 表补 knowledge 列（H4 RAG）
    try:
        conn.execute("ALTER TABLE chatbots ADD COLUMN knowledge TEXT")
    except Exception:
        pass
    # 存量库迁移：多项目（object_types/apps/pipelines 补 project_id）
    for tbl in ("object_types", "apps", "pipelines"):
        try:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN project_id TEXT")
        except Exception:
            pass
    # 默认项目
    cur = conn.execute("SELECT id FROM projects WHERE id='default'").fetchone()
    if not cur:
        conn.execute(
            "INSERT INTO projects (id, name, description, created) VALUES ('default','默认空间','平台初始项目，承载演示数据','2026-08-01T00:00:00Z')"
        )
    conn.commit()
    conn.close()




def set_password(username: str, password: str):
    """修改用户密码（重置后用于改密/管理员重置）。"""
    from .. import security as _sec
    conn = db.get_metadata_conn()
    cur = conn.execute("SELECT 1 FROM users WHERE username=?", (username,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("用户不存在")
    conn.execute("UPDATE users SET password_hash=? WHERE username=?", (_sec.hash_password(password), username))
    conn.commit()
    conn.close()

def create_user(username: str, password: str, role: str = "analyst"):
    """创建一个非管理员用户（幂等）。"""
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?,?,?)",
        (username, security.hash_password(password), role),
    )
    conn.commit()
    conn.close()


def grant(username: str, object_type: str, level: str):
    """授予某用户对某对象类型的 read/write 权限（object_type='*' 表示全部）。幂等。"""
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO grants (username, object_type, level) VALUES (?,?,?)",
        (username, object_type, level),
    )
    conn.commit()
    conn.close()


def user_role(username: str):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row["role"] if row else None


def can_access(username: str, object_type: str, need: str) -> bool:
    """ABAC 核心判定：need ∈ {read, write}。admin 拥有全部权限；其余按 grants 表裁定。

    - read：拥有该对象类型（或 '*'）的 read/write 授权即可。
    - write：必须拥有该对象类型（或 '*'）的 write 授权。
    """
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    if row and row["role"] == "admin":
        conn.close()
        return True
    rows = conn.execute(
        "SELECT object_type, level FROM grants WHERE username=?", (username,)
    ).fetchall()
    conn.close()
    for r in rows:
        if r["object_type"] in ("*", object_type):
            if r["level"] == "write" or (need == "read" and r["level"] == "read"):
                return True
    return False




def audit(username: str, action: str, target: str = "", detail: str = ""):
    """追加不可变审计记录（append-only，仅 INSERT）。"""
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO audit_log (ts, username, action, target, detail) VALUES (?,?,?,?,?)",
        (datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), username, action, target, str(detail)[:500]),
    )
    conn.commit()
    conn.close()


def list_audit(limit: int = 200):
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_object_types_for_user(username: str, project_id: str = None):
    """按 ABAC 过滤：admin 见全部；其余只见有 read 权限的对象类型。可指定项目过滤。"""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    rows = conn.execute("SELECT * FROM object_types ORDER BY name").fetchall()
    conn.close()
    all_types = [dict(r) for r in rows]
    if project_id and project_id != "default":
        all_types = [t for t in all_types if t.get("project_id") == project_id]
    elif project_id == "default":
        all_types = [t for t in all_types if not t.get("project_id") or t["project_id"] == "default"]
    if row and row["role"] == "admin":
        return all_types
    return [t for t in all_types if can_access(username, t["id"], "read")]


def get_object_type(type_id):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM object_types WHERE id=?", (type_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_object_type(ot: dict):
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO object_types
           (id, name, description, backing_table, primary_key, properties, project_id)
           VALUES (?,?,?,?,?,?,?)""",
        (
            ot["id"],
            ot["name"],
            ot.get("description", ""),
            ot["backing_table"],
            ot["primary_key"],
            ot["properties"],
            ot.get("project_id"),
        ),
    )
    conn.commit()
    conn.close()


def list_object_types(project_id: str = None):
    conn = db.get_metadata_conn()
    if project_id and project_id != "default":
        rows = conn.execute("SELECT * FROM object_types WHERE project_id=? ORDER BY name", (project_id,)).fetchall()
    elif project_id == "default":
        rows = conn.execute("SELECT * FROM object_types WHERE project_id IS NULL OR project_id='default' ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT * FROM object_types ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_actions():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM actions ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_action(action_id):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_action(a: dict):
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO actions
           (id, name, description, object_type, operation, parameters, needs_approval)
           VALUES (?,?,?,?,?,?,?)""",
        (
            a["id"],
            a["name"],
            a.get("description", ""),
            a["object_type"],
            a["operation"],
            a["parameters"],
            1 if a.get("needs_approval") else 0,
        ),
    )
    conn.commit()
    conn.close()


def delete_object_type(type_id: str):
    """删除对象类型及其动作/链接/授权/数据表（市场卸载等场景）。"""
    ot = get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'DROP TABLE IF EXISTS "{ot["backing_table"]}"')
    finally:
        dconn.close()
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM actions WHERE object_type=?", (type_id,))
    conn.execute("DELETE FROM links WHERE source_type=? OR target_type=?", (type_id, type_id))
    conn.execute("DELETE FROM grants WHERE object_type=?", (type_id,))
    conn.execute("DELETE FROM retention WHERE object_type=?", (type_id,))
    conn.execute("DELETE FROM type_markings WHERE object_type=?", (type_id,))
    conn.execute("DELETE FROM object_types WHERE id=?", (type_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": type_id}


def delete_action(action_id: str):
    """删除自定义动作。"""
    conn = db.get_metadata_conn()
    cur = conn.execute("SELECT 1 FROM actions WHERE id=?", (action_id,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("动作不存在")
    conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": action_id}


def delete_link(link_id: str):
    """删除链接类型。"""
    conn = db.get_metadata_conn()
    cur = conn.execute("SELECT 1 FROM links WHERE id=?", (link_id,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("链接不存在")
    conn.execute("DELETE FROM links WHERE id=?", (link_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": link_id}


def delete_pipeline(pid: str):
    """删除管道及其运行历史/快照。"""
    conn = db.get_metadata_conn()
    cur = conn.execute("SELECT 1 FROM pipelines WHERE id=?", (pid,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("管道不存在")
    conn.execute("DELETE FROM pipelines WHERE id=?", (pid,))
    conn.execute("DELETE FROM pipeline_runs WHERE pipeline_id=?", (pid,))
    conn.execute("DELETE FROM pipeline_snapshots WHERE pipeline_id=?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": pid}


def set_action_approval(action_id: str, needs: bool):
    conn = db.get_metadata_conn()
    cur = conn.execute("UPDATE actions SET needs_approval=? WHERE id=?", (1 if needs else 0, action_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise ValueError("动作不存在")
    return {"ok": True, "action_id": action_id, "needs_approval": bool(needs)}


def list_users():
    """列出所有用户（username, role）。"""
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT username, role FROM users ORDER BY username").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_role(username: str, role: str):
    conn = db.get_metadata_conn()
    conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()


def delete_user(username: str):
    """删除用户及其授权（不能删除 admin 自身）。"""
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM grants WHERE username=?", (username,))
    conn.execute("DELETE FROM users WHERE username=? AND username<>?", (username, config.ADMIN_USER))
    conn.commit()
    conn.close()


def list_grants():
    """列出全部授权（username, object_type, level）。"""
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT username, object_type, level FROM grants ORDER BY username, object_type"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_grant(username: str, object_type: str):
    conn = db.get_metadata_conn()
    conn.execute(
        "DELETE FROM grants WHERE username=? AND object_type=?", (username, object_type)
    )
    conn.commit()
    conn.close()


def create_link_type(lt: dict):
    """定义链接类型：连接 source_type 与 target_type。

    采用外键(foreign-key)模型：source 表上的一个列 source_fk 引用 target 的主键，
    表达「多个 source 对象关联到同一个 target 对象」。反向遍历即从 target 找所有 source。
    join_table / target_fk 预留给未来的多对多关联表模型。
    """
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO links
           (id, name, source_type, target_type, join_table, source_fk, target_fk, properties)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            lt["id"],
            lt.get("name", lt["id"]),
            lt["source_type"],
            lt["target_type"],
            lt.get("join_table"),
            lt.get("source_fk"),
            lt.get("target_fk"),
            lt.get("properties", "[]"),
        ),
    )
    conn.commit()
    conn.close()


def list_link_types():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM links ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_link_type(link_id):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_links_for_type(type_id):
    """返回与某对象类型相关的所有链接（无论作为 source 还是 target）。"""
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT * FROM links WHERE source_type=? OR target_type=?", (type_id, type_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_pipeline(p: dict):
    conn = db.get_metadata_conn()
    steps = p["steps"]
    if isinstance(steps, (list, dict)):
        steps = json.dumps(steps, ensure_ascii=False)
    conn.execute(
        "INSERT OR REPLACE INTO pipelines (id, name, description, steps, project_id) VALUES (?,?,?,?,?)",
        (p["id"], p.get("name", p["id"]), p.get("description", ""), steps, p.get("project_id")),
    )
    conn.commit()
    conn.close()


def list_pipelines(project_id: str = None):
    conn = db.get_metadata_conn()
    if project_id and project_id != "default":
        rows = conn.execute("SELECT * FROM pipelines WHERE project_id=? ORDER BY name", (project_id,)).fetchall()
    elif project_id == "default":
        rows = conn.execute("SELECT * FROM pipelines WHERE project_id IS NULL OR project_id='default' ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT * FROM pipelines ORDER BY name").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["steps"] = json.loads(d["steps"])
        except Exception:
            pass
        out.append(d)
    return out


def get_pipeline(pid):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM pipelines WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["steps"] = json.loads(d["steps"])
    except Exception:
        pass
    return d


# ---- 活动日志（通知 / 审计，M10 基础） ----
_DUCK_TYPE = {"integer": "INTEGER", "double": "DOUBLE", "boolean": "BOOLEAN", "string": "VARCHAR", "date": "DATE", "timestamp": "TIMESTAMP", "geohash": "VARCHAR", "attachment": "VARCHAR"}


def log_activity(kind: str, message: str):
    """记录一次平台活动（用户/类型/管道/动作/接入等），供通知中心与审计读取。"""
    import datetime
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO activity (ts, kind, message) VALUES (?,?,?)", (ts, kind, message))
    conn.commit()
    conn.close()


def list_activity(limit: int = 50):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT ts, kind, message FROM activity ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 属性编辑（对齐 Foundry 类型详情页的 Properties 面板，45104673） ----
def add_property(type_id: str, prop: dict):
    """为对象类型追加一个属性：DuckDB 表加列 + 元数据 properties 追加。"""
    ot = get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    props = json.loads(ot["properties"])
    key = (prop.get("key") or "").strip()
    if not key:
        raise ValueError("字段 key 必填")
    if any(p["key"] == key for p in props):
        raise ValueError("字段已存在")
    dtype = _DUCK_TYPE.get(prop.get("type"), "VARCHAR")
    title = prop.get("title") or key
    dconn = db.get_duckdb()
    try:
        # 列可能已被外部 SQL 手工添加：存在则跳过 ALTER（避免 Catalog Error）
        cols = {r[1] for r in dconn.execute(f'PRAGMA table_info("{ot["backing_table"]}")').fetchall()}
        if key not in cols:
            dconn.execute(f'ALTER TABLE "{ot["backing_table"]}" ADD COLUMN "{key}" {dtype}')
    finally:
        dconn.close()
    item = {"key": key, "type": prop.get("type", "string"), "title": title, "column": key,
            **({"sensitive": True} if prop.get("sensitive") else {}),
            **({"required": True} if prop.get("required") else {}),
            **({"enum": prop["enum"]} if prop.get("enum") else {}),
            **({"pattern": prop["pattern"]} if prop.get("pattern") else {})}
    props.append(item)
    conn = db.get_metadata_conn()
    conn.execute(
        "UPDATE object_types SET properties=? WHERE id=?",
        (json.dumps(props, ensure_ascii=False), type_id),
    )
    conn.commit()
    conn.close()
    # 新增字段后刷新 CRUD 动作参数，让新列立即可通过标准动作写入
    ensure_crud_actions(type_id, props, ot["primary_key"])
    return {"ok": True, "key": key}


def remove_property(type_id: str, key: str):
    """删除对象类型的一个属性（不能删主键）。"""
    ot = get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    props = json.loads(ot["properties"])
    if not any(p["key"] == key for p in props):
        raise ValueError("字段不存在")
    if key == ot["primary_key"]:
        raise ValueError("不能删除主键字段")
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'ALTER TABLE {ot["backing_table"]} DROP COLUMN "{key}"')
    finally:
        dconn.close()
    props = [p for p in props if p["key"] != key]
    conn = db.get_metadata_conn()
    conn.execute(
        "UPDATE object_types SET properties=? WHERE id=?",
        (json.dumps(props, ensure_ascii=False), type_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "key": key}


def ensure_crud_actions(object_type_id: str, props: list, primary_key: str = "id"):
    """为每个对象类型补齐 create/update/delete 三个标准动作（幂等，可重复调用）。

    这是应用构建（S4）和动作引擎协同的基础：对象类型一旦注册，就天然具备
    完整的增改删写能力，前端/OSDK/生成的应用都能直接复用。
    """
    pk_type = "integer"
    for p in props:
        if p["key"] == primary_key:
            pk_type = p["type"]
            break
    scalar = [{"name": p["key"], "type": p["type"], "required": False} for p in props]

    create_action({
        "id": f"{object_type_id}__create",
        "name": f"Create {object_type_id}",
        "description": "注册自动生成的标准创建动作",
        "object_type": object_type_id,
        "operation": "create",
        "parameters": json.dumps(scalar),
    })
    create_action({
        "id": f"{object_type_id}__update",
        "name": f"Update {object_type_id}",
        "description": "注册自动生成的标准更新动作",
        "object_type": object_type_id,
        "operation": "update",
        "parameters": json.dumps(
            [{"name": "id", "type": pk_type, "required": True}] + scalar
        ),
    })
    create_action({
        "id": f"{object_type_id}__delete",
        "name": f"Delete {object_type_id}",
        "description": "注册自动生成的标准删除动作",
        "object_type": object_type_id,
        "operation": "delete",
        "parameters": json.dumps([{"name": "id", "type": pk_type, "required": True}]),
    })
