# ShuttleUp

ShuttleUp 是一个从多人约时间、查场地、确认订场到 AA 结清的轻量 Web 应用。生产环境由一个 FastAPI 服务提供 API、SSE 和 React 静态文件，状态保存在一个 SQLite 数据卷中。

## 本地开发

需要 Python 3.12、uv、Node.js 22+。

```bash
uv sync --group dev
uv run alembic -c backend/alembic.ini upgrade head
uv run shuttleup admin create
uv run uvicorn shuttleup.app:app --reload --port 8000

npm --prefix frontend ci
npm --prefix frontend run dev
```

Vite 地址为 `http://localhost:5173`，开发时将 API 转发到 8000 端口。生产构建运行：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run build
uv run pytest backend/tests plugins/astrbot_plugin_shuttleup/tests
```

## 服务器部署

完整步骤见 [服务器部署说明](docs/deployment.md)，包含新部署、自动 HTTPS、已有反向代理、SMTP、管理员、备份恢复和现有数据库导入。

```bash
python3 scripts/init-env.py
# 编辑 .env：实际访问地址、邮件服务和管理员邮箱
# 已有 HTTPS 代理：
docker compose up -d --build
# 或使用附带的 Caddy（先配置 SITE_DOMAIN 与 ACME_EMAIL）：
# docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

生成供服务器使用的源码包：`python3 scripts/package-release.py`。输出到忽略目录 `release/`，不包含真实配置、数据库和私有场馆扩展。前端在 Docker 构建阶段编译，运行时只需一个应用容器和持久数据卷。

## AstrBot 插件

将 `plugins/astrbot_plugin_shuttleup` 安装到 AstrBot，配置 HTTPS `base_url`、`bot_key=main` 与服务端相同的 `api_token`。用户可直接在群里 @Bot 发送 `/发起约球 周末夜场`，无需先注册或绑定网页账号。群成员发送 `/羽球 加入` 即可参与；Bot 是和 Web 并列的公共入口，操作同一套活动。私聊 `/羽球 网页` 可通过一次性链接在网页继续同一身份。已有网页账号可在首次使用前选择绑定；网页创建的活动可由主持人在活动页生成群关联码后执行 `/羽球 关联 群绑定码`。

真实 WakeUp 与首个场馆网站的联调输入、限制与验收状态见 `docs/integrations/`。


邮箱注册的 SMTP 配置见 [邮箱注册与发件配置](docs/email-registration.md)。
