# MVP 本地验收记录 · 2026-11-23

代码基线 `b325e9b`，本轮运行代码 `ef8f1af`。Windows x64、Python 3.13.17、Node 24.14.0、npm 11.9.0、Playwright 1.65.2 + 本机 Edge。测试仅使用临时 SQLite、回环 API 和测试模型；不保存或附上令牌、密钥、原始网络包。

| 验收 | 实际结果 |
| --- | --- |
| 旧版真实数据形态 | 从提交 `a88751f` 运行当时的应用代码，用其测试模型在临时库生成三场林悦「我们一般用官方邮箱发通知。」、旧 `disclosure/K04` 只摘「官方邮箱」的记录。新版续训时普通发言的生成和审核均未获得 K04；第一场新复盘不收旧迹，第二场重新有效披露后只引用新回复，第三场已归档 v1 按原样读取。旧迹和原聊天保留。另有 `0001` 至 `head`、旧拒绝范围和旧聊天提交的迁移回归。 |
| 五条线索／显式登记 | K01–K03 各验证实际披露及含糊回复；K04/K05 原回归保留。两个固定选项、聊天只表达意愿、单项确认、整单停止、旧页拒收、明确重启不代交、相同和并发确认不多记均通过。 |
| 构建后的浏览器主线 | 三个角色 → 陈浩邀请、项目愿给／城市暂缓 → 停止／旧页提交被拒 → 重启 → 只点项目、丢失确认响应仍恢复 → 正式决定「仅提交必要资料」并引用本场消息 → 刷新复盘、回到林悦原话；第二场提前结束无正式决定。只勾引文不写理由也能定位，不自动算判断依据。 |
| 失败与幂等 | 在真实连接上阻塞一次生成，中途切角色不显示别人的待发草稿，刷新断开 SSE 后自动读回。重放已完成请求仍只有 1 份回执、2 条消息、2 个事件（含建场）、2 条证据，模型只被调用一轮。去掉终帧、模拟模型超时、刷新后原编号重试也通过；失败轮无正式消息、事件或证据。 |
| 隔离与本地跨源 | 检查两场、三角色各段模型输入，只含本场当前私聊；其他训练凭据不可读、不可引用。Vite 开发页面与不同回环端口的 API 实跑发言、刷新、提前结束和引文定位；精确来源预检放行，其他来源无授权头。此项不是云端或 HTTPS 测试。 |

## 从空目录启动、停止和恢复（已实跑）

1. 将 `ef8f1af` 克隆到一个新临时目录，确认没有 `.venv`、`frontend/node_modules`、`frontend/dist` 或 `data/`。按 README 执行 `py -3.13 run.py --setup --port 54646`（端口可换）。安装 Python 依赖、`npm ci`（51 个包）、生产构建及迁移成功；`.venv/Scripts/python.exe -m alembic current` 返回 `0004_explicit_confirmation (head)`。打开工作台返回 200，通过浏览器建场。
2. 用回环兼容模型（特意采用非 `/v1` 的根地址）经应用 API／生产页面跑过三人共四轮，8 条消息、一项显式确认、正式决定和 K04/K05 证据；浏览器可点回原话。进程退出后不带任何模型配置，用同一端口 `py -3.13 run.py --port 54646` 启动**新的进程**，健康检查显示未配置模型，但同一凭据读回的完整会话 JSON 与重启前相同。
3. 对运行中的默认数据库使用 SQLite `backup` API 生成独立文件，`integrity_check` 为 `ok`，`foreign_key_check` 无行。停服，设置 `SCAMSENSE_DATABASE_URL` 指向恢复副本，第三次启动并比对完整会话仍一致。此处实测的是 SQLite 一致快照与应用恢复，不代表已经验证 Linux 运维命令或云主机。

## 复跑与输出摘要

依赖和可选浏览器安装见 [README](../README.md)。在 Git Bash（macOS/Linux 替换 Python 路径，可去掉 `SCAMSENSE_BROWSER_CHANNEL=msedge` 使用已安装的 Playwright Chromium）：

```sh
npm --prefix frontend run build
SCAMSENSE_TEST_BROWSER=1 SCAMSENSE_BROWSER_CHANNEL=msedge .venv/Scripts/python.exe -m pytest -q
```

- `vue-tsc --noEmit && vite build` 成功；Vite 7.3.8 转换 1578 个模块。生产 JS 119.65 kB（gzip 47.26 kB），CSS 21.14 kB（gzip 5.79 kB）。
- 完整套件：`151 passed, 8 skipped, 1 warning`，含 4 个生产页面浏览器用例。8 个跳过项为原有、显式启用才运行的真实模型 K05 用例；警告为 Starlette TestClient 的 httpx 适配弃用提示。既有 `lucide-vue-next` 安装弃用提示不影响构建，本轮不更换 UI 依赖。

## 本轮没有验证什么

- **真实模型未验证。** 没有为本次安全注入新凭据；没有实际供应商模型 ID、真实对话或真实 K04/K05 结果可报告。测试替身和 `/api/health` 不代表真实 AI 演示已验收。有凭据的审核方按[可选应用冒烟清单](demo.md)记录语义结果，不要求逐字匹配。
- **未上线。** CVM、systemd、Nginx、证书、HTTPS 和 Qoder Sites 公网链路未实测；[部署说明](deploy.md)是交接示例。当前限单实例 SQLite；清除浏览器凭据不能靠数据库备份找回访问权。
