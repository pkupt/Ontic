"""转换函数库（M5 / pb-functions）：以 DuckDB SQL 宏(MACRO)形式提供可在转换 SQL 中
直接调用的标量函数。每次打开 DuckDB 连接时调用 register_functions(conn) 注册。

用 MACRO 而非 Python UDF：零额外依赖（不依赖 numpy）、原生执行、可在任意 SQL 转换中复用。
这是 Pipeline Builder「函数库」的开源等价物：用户无需写 Python，只需在转换 SQL 里用 ont_* 函数。
"""
_MACROS = [
    "CREATE OR REPLACE MACRO ont_upper(s) AS upper(s)",
    "CREATE OR REPLACE MACRO ont_lower(s) AS lower(s)",
    "CREATE OR REPLACE MACRO ont_trim(s) AS trim(s)",
    "CREATE OR REPLACE MACRO ont_len(s) AS length(s)",
    "CREATE OR REPLACE MACRO ont_year(ts) AS CAST(substring(CAST(ts AS VARCHAR), 1, 4) AS INTEGER)",
    "CREATE OR REPLACE MACRO ont_round(x, n) AS round(x, n)",
    "CREATE OR REPLACE MACRO ont_ifnull(x, y) AS coalesce(x, y)",
    "CREATE OR REPLACE MACRO ont_hash(s) AS hash(s)",
]


def register_functions(conn):
    for m in _MACROS:
        conn.execute(m)


def list_functions():
    return [
        {"name": "ont_upper", "signature": "ont_upper(s)", "desc": "字符串转大写"},
        {"name": "ont_lower", "signature": "ont_lower(s)", "desc": "字符串转小写"},
        {"name": "ont_trim", "signature": "ont_trim(s)", "desc": "去除首尾空格"},
        {"name": "ont_len", "signature": "ont_len(s)", "desc": "字符串长度"},
        {"name": "ont_year", "signature": "ont_year(ts)", "desc": "从时间戳/日期取年份(整数)"},
        {"name": "ont_round", "signature": "ont_round(x, n)", "desc": "四舍五入保留 n 位"},
        {"name": "ont_ifnull", "signature": "ont_ifnull(x, y)", "desc": "x 为空时取 y"},
        {"name": "ont_hash", "signature": "ont_hash(s)", "desc": "字符串哈希"},
    ]
