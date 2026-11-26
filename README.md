# ScamSense · 求职判断力训练室

面向校园求职者的虚构训练原型。不鉴定现实招聘方，不收集真实登记材料。Vue 3 + TypeScript + Vite；FastAPI + SQLite / SQLAlchemy + Alembic。

## 先看产品

- **不安装任何依赖：** 双击 `frontend/public/fieldnote.html`。它是只读教学摘录，可以点击证据定位原文，不是实时对话，也不写入训练记录。
- **本地完整工作台：** 安装 Python 3.11+（推荐 3.13）、Node.js 22.12+ 和 npm。在本目录的 PowerShell 中执行：

```powershell
py -3.13 run.py --setup
```

从干净 checkout 的仓库根目录运行即可。首次会建 `.venv`、从 `requirements.txt` 和前端锁文件安装依赖、类型检查及构建 `frontend/dist`、执行 `alembic upgrade head`，再启动同源服务。用浏览器打开 **http://127.0.0.1:8765**，不是双击 `dist/index.html`。以后直接 `py -3.13 run.py`；Ctrl+C 停止。macOS / Linux 将 `py -3.13` 替换为 `python3`。

数据库默认在 `data/scamsense.sqlite3`，不要随发布目录删除；已有库先备份再启动。重启后用**同一浏览器、同一来源（含端口）**打开「训练记录」。后端保留消息、登记和复盘，浏览器本地只保存训练索引及访问凭据；待确认的发言草稿与请求编号临时放在当前标签页，按场次和联系人隔离，确认完成后清除。不要分享浏览器存储。清掉凭据后，单靠训练链接不能恢复访问。

- [3–5 分钟现场演示／可选真模型冒烟清单](docs/demo.md)
- [让同学点邀请链接训练：沿用现有 Railway 服务、保护原库并验收](docs/deploy.md#现有-railway-服务从试用后端切换到班级训练)
- [CVM 生产配置、同源或独立前端、SQLite 备份与恢复](docs/deploy.md#代码数据和进程)
- [2026-11-23 本地 MVP 验收记录：测试替身与未验证项](docs/verification.md)

## 用 Docker 运行预览版

安装支持 Linux 容器的 Docker 后，在仓库根目录执行以下命令；宿主机不需要另装 Node.js 或 Python。镜像从源码构建，服务只向本机开放，SQLite 保存在 `scamsense-data` 命名卷中。GitHub 的打包检查不发布镜像。

```sh
docker build -t scamsense:local .
docker run -d --name scamsense -p 127.0.0.1:8765:8765 -v scamsense-data:/app/data scamsense:local
```

容器先迁移数据库，再启动服务。`docker ps` 显示 `healthy` 后，打开 **http://127.0.0.1:8765**。日常停用和续用分别执行 `docker stop scamsense`、`docker start scamsense`；更新前备份数据，重建时沿用原卷、原端口和浏览器，不要删除数据卷。默认不连接模型；如需真实对话，先在宿主机安全设置下节的模型变量，再在 `docker run` 的镜像名前加 `-e OPENAI_API_KEY -e OPENAI_BASE_URL -e OPENAI_MODEL`，不在命令里写密钥值。

**复验数据是否保留：** 构建后，在有 Docker 和 Python 3.11+ 的机器上运行 `python3 tests/docker_preview.py scamsense:local`（Windows 用 `py -3.13` 替代 `python3`）。脚本只使用临时卷和随机本机端口：检查生产页面和迁移，提交一份决定，移除容器，再用新容器和原凭据读回整场复盘。验收结束会清理测试资源，不使用 `scamsense-data` 或真实模型。

## 真实对话配置

只在**后端进程环境**设置以下变量，然后重新启动后端。不要把密钥放进聊天、前端变量、源码或命令行参数。`OPENAI_API_KEY` 建议通过本机密钥管理或进程环境注入；不建议把明文密钥写入 shell 历史。

| 环境变量 | 含义 |
| --- | --- |
| `OPENAI_API_KEY` | 本地或 Render 的远程模型密钥。使用本机回环模型可不设。 |
| `SCAMSENSE_DEEPSEEK_API_KEY` | Railway 班级版专用的服务端密钥，只连 DeepSeek 官方接口。不要把它填到给学生的邀请链接里。 |
| `OPENAI_BASE_URL` | 供应商给出的 Chat Completions API 根地址，不含 `/chat/completions`；应用只拼接这个端点。根地址是否包含 `/v1` 取决于服务商，远程必须用 HTTPS。 |
| `OPENAI_MODEL` | 服务实际支持的模型 ID，默认 `gpt-4o-mini`；需支持 Chat Completions 的 `json_object` 输出。 |
| `SCAMSENSE_DATABASE_URL` | 可选，SQLite 连接串；默认持久化到 `data/scamsense.sqlite3`，自定义路径须先创建父目录。 |

未配置时仍可进入工作台、切换角色、查看只读案例、结束并复盘；发送发言会明确失败，不保存伪回复。`/api/health` 只表示配置是否存在，不代表模型可达。每轮通过同一模型分别执行理解、角色生成、独立语义校验三次调用，可能产生模型费用；只发送当前角色的必要历史。疑似敏感格式会被拦截，这不是对所有个人信息的完备检测。

## 体验一条完整证据链

1. 进入训练，选择王宇，询问他是否亲自核实过群内转发。不要求输入任何真实资料。
2. 只有回复明确披露本人未核实才记录 K05；只说「在群里看到」不算。再用自己的话分析这条消息的局限。
3. 点击「作出决策」，可写判断理由、引用本场原文，再查看复盘。「提前结束训练」不会生成正式招聘决定。
4. 从复盘点击「定位原话」回到对应角色和消息。刷新后可恢复记录；清除浏览器本地数据会丢失访问凭据。

## 工程与验证

- `backend/`：请求回执、私聊编排、事实权限、模型适配与复盘。会话凭据只存摘要；同场限一个在途请求；通过校验后事务性提交正文、事件与证据。相同标识和内容重发不重复生成。
- `migrations/`：数据库迁移。`frontend/`：工作台、训练记录、三个私聊、终局与复盘。
- `tests/`：临时 SQLite 与仅测试使用的模型替身。已安装依赖后运行 `.\.venv\Scripts\python.exe -m pytest -q`。前端类型检查及构建：`npm --prefix frontend run build`。
- 前端热更新：先运行后端，再执行 `npm --prefix frontend run dev`；开发代理指向 8765。独立部署前端时可在**构建前**配置公开地址 `VITE_API_BASE_URL`（不含 `/api`），后端 `SCAMSENSE_WEB_ORIGIN` 配置允许的单一前端来源。Railway 班级入口使用现有持久卷和服务端 DeepSeek 配置；请分别验证页面可打开、受邀开场和真实模型回复，健康检查不能替代对话验收。

### 可复跑的浏览器验收（可选、只用测试替身）

先完成 `run.py --setup`，退出本地服务也可运行。以下为 PowerShell 命令；测试只在回环地址启动临时 API、测试模型和独立 SQLite，不读取真实模型密钥。

```powershell
.\.venv\Scripts\python.exe -m pip install 'playwright>=1.51,<2'
.\.venv\Scripts\python.exe -m playwright install chromium
npm --prefix frontend run build
$env:SCAMSENSE_TEST_BROWSER='1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:SCAMSENSE_TEST_BROWSER
```

已有 Microsoft Edge 的机器可跳过 Chromium 下载，在同一终端设置 `$env:SCAMSENSE_BROWSER_CHANNEL='msedge'`。Linux/macOS 用 `.venv/bin/python` 和 `SCAMSENSE_TEST_BROWSER=1 .venv/bin/python -m pytest -q`。上述完整套件默认跳过真实供应商用例；真模型验收应单独走[应用冒烟清单](docs/demo.md)，不把测试替身当现场 AI。

### 现场常见问题

| 现象 | 怎么处理 |
| --- | --- |
| 没有可执行的 Python／npm、前端 404 | 核实 Python 和 Node 版本、安装 `venv` 支持；从仓库根目录重跑 `run.py --setup`，确认有 `frontend/dist/index.html`。 |
| 端口占用／找不到上场 | `run.py --port 8766` 可换端口；回看旧场请用原来的协议、主机、端口和浏览器，并确认后端使用同一 SQLite 文件。|
| 启动时报无法打开数据库 | 自定义 SQLite 路径先建父目录，保证运行账号可读写；不要新建空库冒充恢复。|
| 后端在线但模型未配置／本轮失败 | `/api/health` 的 `model_configured` 是配置检查，不验证模型权限、余额、JSON 输出或联网。核对供应商根地址、模型名、授权和网络后重启；不贴密钥。只有实际完成应用私聊、审核和复盘，才算真模型验过。|
| 发送时断线、刷新或模型超时 | 回到该场该角色，先等「正在处理」消失；只核对后端已存的消息。若仍无完成记录，保留原文点「发送」重试；不是新增一轮时不要改写重发。模型/校验失败不落半轮。非正常终止服务后，正在处理的锁最多约 200 秒到期。|
| 登记按钮消失／确认时网络中断 | 核对陈浩已实际邀请、整单未停止且训练未结束。刷新看已提交项；未提交可再点同一选项，已提交不会增加第二条记录。重启登记不代提交。 |

## 未冻结的业务规则

以 `docs/mvp-architecture.md` 为设计依据。训练仅采用事件驱动的粗粒度阶段；终局文案和可选理由是可调整的原型交互。陈浩实际发出邀请后，只有项目经历（`虚构项目 A`）与所在城市（`虚构城市 B`）两项可分别回应。聊天只记意愿，不收件。只有在陈浩私聊点击「提交虚构项目 A」或「提交虚构城市 B」才会提交对应项；不发送消息，不调用模型，重复点击不多记。停止整单后仍可聊天，经审核的明确重启只恢复登记，不需要再次邀请。陈浩私聊和复盘区分显式确认与旧版聊天提交，暂缓、拒绝或终局「仅提交必要资料」都不会增加或删除已有提交。其余登记项未开放，不采集真实资料。四维权重已落实，精确评分档位、锚点及门槛未冻结；有原文时标为「已有依据 · 待定标」，缺证据标为「证据不足」，不产生数值维度分和总分。