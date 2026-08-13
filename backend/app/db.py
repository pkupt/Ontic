"""数据库连接管理：元数据仓(SQLite) + 数据平面(DuckDB)。"""
import sqlite3
import duckdb
from . import config


def get_metadata_conn():
    """返回带 dict 行工厂的 SQLite 连接。调用方负责 close()。"""
    conn = sqlite3.connect(config.METADATA_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_duckdb():
    """返回 DuckDB 连接（数据平面 / 对象集下推目标）。调用方负责 close()。"""
    return duckdb.connect(config.DUCKDB_PATH)
