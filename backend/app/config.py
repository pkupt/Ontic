"""运行时配置。所有可调项均来自环境变量，默认值仅用于本地开发。"""
import os
from pathlib import Path

# ontic/  (backend/app/config.py -> parent.parent = ontic)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = Path(os.environ.get("ONTIC_DATA_DIR", BASE_DIR / "data"))
FRONTEND_DIR = Path(os.environ.get("ONTIC_FRONTEND_DIR", BASE_DIR / "frontend"))

SECRET_KEY = os.environ.get("ONTIC_SECRET_KEY", "dev-secret-change-me-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ONTIC_TOKEN_TTL", "1440"))

# 运行环境：dev（默认，宽松）| prod（生产，强制安全项）
ENV = os.environ.get("ONTIC_ENV", "dev").lower()
_DEFAULT_SECRET = "dev-secret-change-me-in-prod"
if ENV == "prod" and (not SECRET_KEY or SECRET_KEY == _DEFAULT_SECRET):
    raise RuntimeError(
        "[production] 必须设置强 ONTIC_SECRET_KEY（环境变量）；拒绝使用默认密钥启动。"
    )

ADMIN_USER = os.environ.get("ONTIC_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ONTIC_ADMIN_PASSWORD", "admin123")

# 元数据仓（对象类型/链接/动作/用户定义）用 SQLite；数据平面用 DuckDB。
METADATA_PATH = str(DATA_DIR / "metadata.db")
DUCKDB_PATH = str(DATA_DIR / "ontic.duckdb")

DATA_DIR.mkdir(parents=True, exist_ok=True)
