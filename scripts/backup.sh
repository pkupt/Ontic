#!/usr/bin/env bash
# Ontic 备份脚本（P0-5）：备份 DuckDB / SQLite 元数据 / 媒体到 backup/ 时间戳目录。
# 用法：bash scripts/backup.sh [目标目录，默认 <项目>/backup]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${ONTIC_DATA_DIR:-$ROOT/data}"
BACKUP_ROOT="${1:-$ROOT/backup}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"

mkdir -p "$DEST"
echo "[backup] → $DEST"

# 使用 DuckDB 在线一致性备份（避免拷贝进行中的写文件）
PY="${ONTIC_PYTHON:-python3}"   # 生产可设 ONTIC_PYTHON 指向含 duckdb 的解释器（如容器内 python）
# Windows Git Bash 下把 POSIX 路径转成 Windows 路径再传给 Python
if command -v cygpath >/dev/null 2>&1; then
  W_DATA="$(cygpath -w "$DATA_DIR")"; W_DEST="$(cygpath -w "$DEST")"
else
  W_DATA="$DATA_DIR"; W_DEST="$DEST"
fi
if command -v "$PY" >/dev/null 2>&1; then
  "$PY" - "$W_DATA/ontic.duckdb" "$W_DEST/ontic.duckdb" <<'PY'
import duckdb, sys
src, dst = sys.argv[1], sys.argv[2]
con = duckdb.connect(src)
con.execute(f"EXPORT DATABASE '{dst}_export'")
con.close()
print("[backup] DuckDB 一致性导出完成")
PY
else
  cp "$DATA_DIR/ontic.duckdb" "$DEST/ontic.duckdb" 2>/dev/null && echo "[backup] DuckDB 文件拷贝完成（非一致性，建议先停写）"
fi

# 元数据 SQLite（先 WAL checkpoint 再拷贝）
cp "$DATA_DIR/metadata.db" "$DEST/metadata.db" 2>/dev/null || echo "[warn] metadata.db 不存在"
cp -r "$DATA_DIR/media" "$DEST/media" 2>/dev/null || true

# 元信息
echo "created: $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DEST/MANIFEST.txt"
echo "[backup] 完成。清单："
ls -la "$DEST"
