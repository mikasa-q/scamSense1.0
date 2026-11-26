# 部署准备：单实例，SQLite 持久化

给同学发完整的班级邀请，不要发本机地址、GitHub 仓库、站点管理台或自己的聊天页。

## 班级入口与验收（2026-11-26，北京时间）

- **现在发给同学：** 使用组织者本机 `data/classroom-invitation.txt` 中的 Railway 完整邀请。网页和 API 都在 Railway，已通过真实 DeepSeek 对话、刷新和复盘验收；学生不需要模型密钥。
- **原 Qoder Sites 入口：** [ScamSense 求职判断力训练室](https://scamsense-lab-cnexhxc1kvo.qoder.zone) 已发布同一班级前端。发布时为私有，随后核对时已允许匿名打开网页；这不代表可以无邀请开场或读取别人的记录。`data/classroom-invitation-qoder.txt` 是同一邀请码对应的 Sites 链接。站点访问权限和新建训练的邀请不是一回事；邀请文件均不进 Git 或发布包。浏览器的训练凭据按域名保存，从哪里开的训练就从哪里回看。

| 本次 Sites 同步 | 实测结果 |
| --- | --- |
| 发布版本 | 原项目、原域名，平台确认已发布；发布首页与本地构建指纹一致。只上传首页、教学示例、JS、CSS 四个文件。 |
| Railway 连接 | 健康请求及带 `Authorization`、`Content-Type` 的建场预检均为 200，允许来源精确匹配 Sites 域名；未获准的来源预检为 400，没有允许来源头。没有改动后端、数据库或密钥。 |
| 浏览器训练流程 | 本地测试验证无邀请拒绝、受邀建场、刷新和跨浏览器隔离。Sites 发布时的登录限制与后来的公开网页分别核对过：公开后可匿名读取邀请、连接 Railway 健康接口。没有在 Sites 入口重新验收收费对话。 |

再次同步时，构建单独的 Sites 输出，保留 Railway 的同源构建：`VITE_API_BASE_URL=https://api-production-1b849a94.up.railway.app npm --prefix frontend run build -- --outDir dist-sites`。只将 `frontend/dist-sites` 发布到**同一项目**，不要为同步代码更改站点访问权限。给同学发组织者保留的完整邀请，不要复制打开后已移除邀请片段的聊天页地址。

## 现有 Railway 服务：从试用后端切换到班级训练

沿用 `production` 的 `api` 服务、原公网域名和挂在 `/data` 的 `api-volume`。这个项目不需要新建服务、域名或磁盘；Railway 管理页不是发给同学的邀请。

1. 现有试用版配置了 IP 白名单（`SCAMSENSE_TRIAL_IPS`）。保留该变量，旧镜像回退时仍使用原规则。新镜像看到旧变量时，除非站主显式选择 `SCAMSENSE_ACCESS_MODE=classroom`，否则在迁移前就停止；显式切换后仍须同时满足随机邀请、原库和 DeepSeek 配置检查。新入口用班级邀请而非来源 IP 决定能否开场。若还需要限制来源 IP，不要切到此入口。不要应用或丢弃控制台上其他服务的待发布改动。
2. 先核实原库的准确文件名和挂载、应用用户的读写权限，按站主的既有备份流程留可恢复的副本；若备份需要另付费先确认。`SCAMSENSE_DATABASE_URL` 必须指向 `RAILWAY_VOLUME_MOUNT_PATH` 内**原来已迁移的库**，不要照搬 Render 的 `/app/data`。没有找到原库时不会另建空库。容器使用平台的 `PORT` 和单工作进程。
3. 将 `SCAMSENSE_ACCESS_MODE` 设为 `classroom`。班级邀请 `SCAMSENSE_CLASS_INVITE` 独立随机生成；DeepSeek 密钥由站主在 `api → Variables` 单独录入为 **`SCAMSENSE_DEEPSEEK_API_KEY`**，建议设为 Sealed。这个名字不会启用现有试用版的模型，Railway 班级版只把它发送到 `https://api.deepseek.com`。不要公开邀请、不要把模型密钥发到聊天或放入前端，不要点击混有其他服务变更的全局 Deploy。班级默认限额见下文。每次真实训练可能有模型费用，试用计划也不保证永久在线。
4. 仅定向发布到既有 `api` 服务，确认原盘仍在。用未登录管理台的浏览器验证首页、静态资源和 `/api/health` 的 `invite_required=true`；确认没邀请就不能开场。用于班内私发的格式是服务的 HTTPS 地址加 `/#invite=` 和班级邀请值。`model_configured=true` 不证明真实回复；在授权 DeepSeek 用量后才做真实对话和复盘验收。

## Render 班级邀请链接

以下是**另选 Render 时**的方案，不是现有 Railway 服务的发布步骤。

选这条路径后，网页、API 和数据库都在云端；同学不用安装软件、登录 Render 或填写 DeepSeek 密钥。

1. **先确认预算和代码版本。** 按 2026-11-25 的 [Render 定价](https://render.com/pricing)，Hobby 工作区无月费；0.5 CPU / 512 MB 单实例约 7 美元/月，1 GB 持久盘 0.25 美元/月，连续运行的基础费用约 **7.25 美元/月**，不含税、超额流量和 [DeepSeek 用量](https://api-docs.deepseek.com/quick_start/pricing)。免费实例不能挂这块盘。只有得到授权才提交、推送包含 `render.yaml` **及班级准入代码**的版本；不需要合进主版本、发布镜像或上传本机数据库。
2. **由站主授权。** 在自己的 [Render 控制台](https://dashboard.render.com/) 选择 Hobby 工作区，GitHub 应用仅授权这个仓库。选择 **New → Blueprint**，选含本次改动的分支和根目录 `render.yaml`。确认将创建**新的** Web Service 而非更改同名旧服务，只有一个新加坡实例、一个挂在 `/app/data` 的 1 GB 盘，没有其他资源；核对平台显示的金额后再点击创建。不要部署只有打包检查、尚无班级保护的版本。
3. **分开两种密钥。** 只在 Render 的受保护设置中填 `OPENAI_API_KEY`（建议用专用、未公开的 DeepSeek 密钥），API 根地址和模型已在模板中设为 `https://api.deepseek.com` / `deepseek-flash`。`SCAMSENSE_CLASS_INVITE` 则由 Render 随机生成，**不是模型密钥**；两者都不进 Git、构建参数引用、`VITE_*` 或日志。Docker 在挂盘后的启动阶段迁移 SQLite，再启动单个非 root 进程。若迁移报不可写，先核实挂载与运行用户权限，不要改用临时盘或开放所有权限。
4. **拿到班级链接。** 服务显示 Live 后，从控制台复制实际的 HTTPS 服务地址，在末尾加上 `/#invite=` 和 **`SCAMSENSE_CLASS_INVITE` 的值**（保留 `+`、`/`、`=` 字符）；只在班内私发完整链接，不要把它或密钥发到问题区。打开后点「进入训练」。邀请放在 `#` 后，不随页面 GET 发送；网页读取后移除地址片段，只在建场时用请求头出示。请发原邀请链接，而不是复制去掉邀请的地址或你自己的聊天页面。只打开链接不会占用训练名额。
5. **外网验收后再分发。** 用新的浏览器配置文件或手机移动网络打开裸地址，确认不能新建；再用实际邀请链接建场，向王宇问「这条转发你亲自向招聘方核实过吗？」，等进度和一条通过审核的角色回复。结束、刷新并回看；另一个浏览器不能通过聊天地址读到该记录。一次真实回合最多 3 次收费调用。仅显示网页、`/api/health` 成功或 `model_configured=true` **都不算**。上线验收还应在维护窗口保留原磁盘、重启服务，用原浏览器确认回复与复盘仍在。

默认**整班累计** 40 场（`SCAMSENSE_MAX_SESSIONS`）、240 次对话尝试（`SCAMSENSE_MAX_TURNS`），每场最多 20 次（`SCAMSENSE_TURNS_PER_SESSION`），同时最多 3 场在生成。模型/校验失败后重新生成也计数；取回已完成的同一请求不重复扣，浏览、结束和复盘不扣。班级模式每次模型调用最多输出 2048 tokens。这是本站的次数和输出长度上限，不是美元账单上限；泄露的模型密钥被直接用于供应商 API 不受本站限制。名额按场而非按人，关掉浏览器不释放；重启、重新部署到同一块盘、轮换邀请都不清零。需要继续办班时显式调高累计上限并重启，不要删库。若链接外泄，轮换班级邀请以阻止旧链接再开场；已开场仍可用自己的凭据，要紧急停用**新的模型调用**则把 `SCAMSENSE_MAX_TURNS` 设为 `0` 并应用，不影响回看。恢复旧备份也会恢复旧计数，重新开放前须核对预算。

## 单台 CVM

以下供已有 CVM 的运维者参考。示例域名为占位符；腾讯云、systemd、Nginx 和 HTTPS 未在目标环境实测。公开招生前也须按上文设置 `SCAMSENSE_ACCESS_MODE=classroom` 和独立随机邀请，不要把无准入的本地服务直接开放到公网。

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
