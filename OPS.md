# Ontic 运维手册（OPS）

> 生产部署 / 升级 / 备份 / 恢复 / HTTPS / 限流 / 数据约束

## 1. 生产部署

```bash
# 1) 配置生产环境
cat > .env <<'EOF'
ONTIC_ENV=prod                       # 生产模式：强制强密钥，拒绝默认值
ONTIC_SECRET_KEY=<生成强随机密钥>     # openssl rand -hex 32
ONTIC_ADMIN_PASSWORD=<初始管理员密码>  # 首次启动后请立即在界面修改
ONTIC_CORS_ORIGINS=https://your.domain
EOF

# 2) 构建并启动
docker compose up -d --build

# 3) 反向代理（TLS）：见 deploy/nginx.conf.example 或 deploy/Caddyfile.example
#    Caddy 一行自动 HTTPS：<domain> { reverse_proxy localhost:8080 }
```

## 2. 升级

```bash
git pull
docker compose build --pull
docker compose up -d
# 数据在 ./data（volume），升级不丢数据。升级前先备份（见下）。
# schema 变更由启动时自动迁移（metadata.py init_metadata，try/except ALTER）。
```

## 3. 备份与恢复

```bash
# 备份（一致性 DuckDB 导出 + SQLite + 媒体）
ONTIC_PYTHON=/path/to/python-with-duckdb bash scripts/backup.sh
# 建议 cron：0 2 * * *  cd /opt/ontic && ONTIC_PYTHON=$(which python3) bash scripts/backup.sh >> /var/log/ontic-backup.log 2>&1

# 恢复（交互确认）
bash scripts/restore.sh backup/20260814_115343 --force
```

## 4. 安全基线（生产必做）

| 项 | 说明 | 状态 |
|---|---|---|
| 强密钥 | `ONTIC_ENV=prod` 下默认密钥直接拒绝启动（fail-closed） | ✅ 内置 |
| 密码策略 | 创建/改密：长度≥8 且含字母数字 | ✅ 内置 |
| 登录限流 | 同 IP 5 次失败锁 15 分钟（内存，重启清零） | ✅ 内置 |
| 默认密码 | 前端横幅提示 admin 改默认密码；`/api/me` 返回 `default_pw` | ✅ 内置 |
| HTTPS | nginx/Caddy 反代 TLS 终结 | 示例就绪 |
| 审计 | 授权/改角色/删资源/重置密码写 `audit_log`（append-only） | ✅ 内置 |
| 凭据加密 | 连接器密码/令牌加密落库（AES-GCM 计划见路线图） | 轻量版 |

## 5. 数据约束（重要）

- **DuckDB 单写者**：同一时刻只允许一个进程写 DuckDB。多副本/多 worker 部署需前置写代理，否则可能文件锁冲突。当前 compose 为单实例单进程（uvicorn 默认单 worker）。
- **持久化目录**：`data/`（ontic.duckdb + metadata.db + media/）。容器重建不丢，**请勿删除**。
- 磁盘安全：DuckDB 明文落盘；敏感数据建议配合磁盘加密（LUKS/BitLocker）。

## 6. 监控

- 健康检查：`GET /api/health`、`GET /api/health/deep`
- 指标（Prometheus）：`GET /api/metrics`（请求数/错误/延迟 p50/p95/status 分布/uptime）
- 结构化日志：服务输出 JSON 行（ts/level/event/method/path/status/dur_ms）
- 审计：`GET /api/audit`（admin）

## 7. 常见操作

```bash
# 查看日志
docker compose logs -f

# 进入容器
docker compose exec ontic sh

# 数据在宿主机 ./data 直接可读（DuckDB CLI 可查）
```
