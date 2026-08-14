#!/usr/bin/env bash
# Ontic 恢复脚本（P0-5）：从指定备份目录恢复 DuckDB / SQLite / 媒体。
# 用法：bash scripts/restore.sh <备份目录> [--force]
# 警告：恢复会覆盖当前数据，务必先备份现状。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${ONTIC_DATA_DIR:-$ROOT/data}"
SRC="${1:?用法: bash scripts/restore.sh <备份目录> [--force]}"
FORCE="${2:-}"

if [ ! -f "$SRC/metadata.db" ]; then
  echo "[错误] $SRC 不是有效备份（缺 metadata.db）"; exit 1
fi

if [ "$FORCE" != "--force" ]; then
  echo "⚠️  恢复将覆盖当前 data/ 目录。当前数据备份到 data/.pre_restore_$(date +%s) 后继续？(yes/no)"
  read -r confirm
  [ "$confirm" != "yes" ] && { echo "已取消"; exit 0; }
fi

# 保护现场
if command -v python3 >/dev/null 2>&1; then
  python3 - "$DATA_DIR/ontic.duckdb" "$DATA_DIR/.pre_restore_$(date +%s).duckdb" <<'PY'
import duckdb, sys
con = duckdb.connect(sys.argv[1]); con.execute(f"EXPORT DATABASE '{sys.argv[2]}_exp'"); con.close()
PY
fi

cp "$SRC/metadata.db" "$DATA_DIR/metadata.db"
cp -r "$SRC/media" "$DATA_DIR/media" 2>/dev/null || true
echo "[restore] metadata.db / media 已恢复。"

# DuckDB：优先用 EXPORT 目录导入，否则回退文件拷贝
if [ -d "${SRC}/ontic.duckdb_export" ]; then
  python3 - "$SRC/ontic.duckdb_export" "$DATA_DIR/ontic.duckdb" <<'PY'
import duckdb, sys, os
src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst): os.remove(dst)
con = duckdb.connect(dst)
con.execute(f"IMPORT DATABASE '{src}'")
con.close()
PY
  echo "[restore] DuckDB 已从一致性导出恢复。"
elif [ -f "$SRC/ontic.duckdb" ]; then
  cp "$SRC/ontic.duckdb" "$DATA_DIR/ontic.duckdb"
  echo "[restore] DuckDB 文件已恢复（文件拷贝模式）。"
else
  echo "[warn] 备份中未发现 DuckDB 导出/文件，跳过。"
fi
echo "[restore] 完成。请重启 Ontic 服务。"
