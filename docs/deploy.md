# 部署准备：单台 CVM，SQLite 持久化

以下是供获授权运维者采用的最小配置，**不是上线记录**。本次交付不创建云资源、不配置 DNS、不申领证书。示例域名为占位符。Windows 本地生产构建与运行见 README；腾讯云、systemd、Nginx 和 HTTPS 未在目标环境实测。

## 代码、数据和进程

Linux CVM 需 Python 3.11+（推荐 3.13）、带 venv 的 Python、Node 22.12+、npm，以及备份用的 `sqlite3` CLI。示例把已审查的 checkout 放在 `/opt/scamsense`，服务账号 `scamsense` 只读代码；数据库在独立的 `/var/lib/scamsense`，**不放在发布目录、静态目录或临时盘**。在代码目录用发布账号构建：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci --ignore-scripts --no-audit --no-fund
npm --prefix frontend run build
```

由管理员预建不可登录的 `scamsense` 系统账号及 `/etc/scamsense/`。示例 `/etc/scamsense/backend.env` 由 root 持有、权限 `0600`，不进版本库；模型密钥通过受控的服务环境注入。不要照抄假值启动真模型。

```ini
SCAMSENSE_DATABASE_URL=sqlite:////var/lib/scamsense/scamsense.sqlite3
# OPENAI_BASE_URL=https://provider.example.invalid/provider-api-root
# OPENAI_MODEL=provider-assigned-model-id
# OPENAI_API_KEY=<由管理员安全注入的新密钥>
# 仅分离前端时设置，必须是精确来源，不是 API 域名或通配符：
# SCAMSENSE_WEB_ORIGIN=https://your-frontend.example.invalid
```

以 `scamsense` 身份、带相同环境和可写数据目录手动验证时，生产命令为 `.venv/bin/python -m alembic upgrade head`，然后 `.venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8765 --workers 1 --no-access-log`。不要运行 Vite dev server、自动重载或多机共享 SQLite。保留同一数据库、同一前端来源与浏览器，重启不影响已归档的会话。

`/etc/systemd/system/scamsense.service` 示例：

```ini
[Unit]
Description=ScamSense training service
After=network.target

[Service]
User=scamsense
Group=scamsense
WorkingDirectory=/opt/scamsense
EnvironmentFile=/etc/scamsense/backend.env
StateDirectory=scamsense
StateDirectoryMode=0700
UMask=0077
ExecStartPre=/opt/scamsense/.venv/bin/python -m alembic upgrade head
ExecStart=/opt/scamsense/.venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
Restart=on-failure
TimeoutStopSec=210
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
```

获授权安装后 `systemctl daemon-reload`、`systemctl enable --now scamsense`；先在 CVM 上检查 `curl --fail http://127.0.0.1:8765/api/health`。返回代表后端能响应，`model_configured` 不探测供应商连通性。用 `systemctl status scamsense` 看状态；不打开 SQL/HTTP debug，不记录请求体、Authorization、令牌、模型输入输出或全量聊天。

## Nginx、TLS 与两种前端

示例放入 Nginx 的 `http` 上下文，替换域名和已授权获得的证书文件；仅将 443（如需跳转再开 80）暴露给访问者，不开放 8765。先 `nginx -t` 再由管理员重载。

```nginx
server {
    listen 80;
    server_name training.example.invalid;
    access_log off;
    return 301 https://training.example.invalid$request_uri;
}
server {
    listen 443 ssl;
    server_name training.example.invalid;
    ssl_certificate     /etc/nginx/tls/scamsense/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/scamsense/privkey.pem;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 210s;
        gzip off;
    }
}
```

| | 前端和 API 同源（首选） | Qoder Sites 独立静态前端 |
| --- | --- | --- |
| 构建 | 不设 `VITE_API_BASE_URL`。上面的 FastAPI 同时提供 `frontend/dist` 和 `/api`。 | 构建前设 `VITE_API_BASE_URL=https://api.example.invalid`，**不含 `/api`**，再构建 `frontend/dist`；只把静态产物交给获授权的站点发布者。改 API 地址须重建。 |
| 服务端 | 不设 `SCAMSENSE_WEB_ORIGIN`，不需要跨域。 | API 由 CVM 提供 HTTPS；后端设 `SCAMSENSE_WEB_ORIGIN` 为实际站点的**精确来源**（协议、域名、非默认端口；无路径），重启。允许 GET/POST 和 Authorization、Content-Type 的预检；不要改成 `*`。 |
| 注意 | Nginx、上游网关或 CDN 均不能缓冲 `/api/.../turns` 的 SSE 或缓存私有响应。 | 从 HTTPS 页面不能调用 HTTP API。浏览器直连 API 代理，仍需禁用 SSE 缓冲；模型 Key 永不放到 `VITE_*`。更换站点来源不会迁移浏览器凭据。 |

目标环境放行前：实际从目标页面建场、查看三段进度是否陆续到达（不是等最后一次性返回）、刷新并回看，验证允许来源能通信且其他来源没有 `Access-Control-Allow-Origin`。代理、TLS、云账号和公网真机测试不能用本地结果代替。

## SQLite 备份、恢复与回退

备份包含虚构聊天和凭据摘要，限制读取权限，不上传到公开网盘。不要一边服务写入一边只复制主 `.sqlite3` 文件；SQLite 在线备份会获得一致快照。如下命令在 CVM 本地执行，路径需与实际配置一致：

```sh
sudo install -d -m 0700 -o scamsense -g scamsense /var/backups/scamsense
backup=/var/backups/scamsense/training-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
sudo -u scamsense sqlite3 -readonly /var/lib/scamsense/scamsense.sqlite3 '.timeout 10000' ".backup '$backup'"
sudo chmod 0600 "$backup"
sudo -u scamsense sqlite3 -readonly "$backup" 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version_num FROM alembic_version;'
```

完整性应为 `ok`、外键检查无行，另有一行迁移版本。保留受访问控制的异地备份；升级前或首次迁移历史库前也先备份。

1. 维护窗口内停止服务，保留现库及相关 WAL/journal 文件不动。选一份已校验的备份，用 `install -o scamsense -g scamsense -m 0600` 将其复制到数据目录下**新的、未使用过的文件名**（例如 `restored-20261123.sqlite3`）。不要把旧 WAL 放到新文件旁边。
2. 在受保护的环境文件中将 `SCAMSENSE_DATABASE_URL` 指向新文件。用与备份兼容的代码启动服务；`ExecStartPre` 迁移、`/api/health` 响应后，在原浏览器同源打开训练记录。核对已知会话的三角色消息、已提交项、正式决定及引文定位。不在日志中打印正文。数据库备份**不含浏览器的明文访问凭据**。
3. 不一致就停服，切回原数据库路径和匹配的代码版本，不覆盖原数据。恢复到历史备份不包含备份之后的新训练；先确认影响，再开放访问。
