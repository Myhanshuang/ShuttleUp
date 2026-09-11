# ShuttleUp

ShuttleUp 是一个从多人约时间、查场地、确认订场到 AA 结清的轻量 Web 应用。生产环境由一个 FastAPI 服务提供 API、SSE 和 Vue 静态文件，状态保存在一个 SQLite 数据卷中。

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

## 单机部署

复制 `.env.example` 为 `.env`，至少替换 `APP_BASE_URL`、`APP_SECRET` 和 `ASTRBOT_MAIN_TOKEN`。随机密钥可以用 `openssl rand -hex 32` 生成。然后：

```bash
docker compose build
docker compose up -d
docker compose exec app shuttleup admin create
curl http://127.0.0.1:8000/readyz
```

容器启动时先运行 Alembic 迁移，再启动一个 Uvicorn worker。镜像构建会编译 SQLite 3.51.3 并实际断言运行版本。前端只在构建阶段需要 Node；生产镜像不包含 Node 或浏览器。

公网访问应放在现有 HTTPS 反向代理后。Nginx 的 SSE 路由需要关闭缓冲：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 75s;
}
```

将 `FORWARDED_ALLOW_IPS` 设为可信代理地址，不要在公网环境使用任意来源。

## 备份与恢复

在线备份使用 SQLite backup API，不直接复制正在写入的数据库文件：

```bash
docker compose exec app shuttleup backup /data/backup-2026-09-11.db
docker compose cp app:/data/backup-2026-09-11.db ./backup-2026-09-11.db
```

恢复时先停止服务，保留当前文件，再放入备份并启动：

```bash
docker compose down
docker run --rm -v shuttleup_shuttleup-data:/data -v "$PWD":/backup alpine cp /backup/backup-2026-09-11.db /data/shuttleup.db
docker compose up -d
```

恢复后检查 `/readyz` 并登录核对最近一场活动。请同时在宿主机或对象存储中保存备份，数据卷本身不算备份。

## AstrBot 插件

将 `plugins/astrbot_plugin_shuttleup` 安装到 AstrBot，配置 HTTPS `base_url`、`bot_key=main` 与服务端相同的 `api_token`。用户在网页个人设置生成绑定码后私聊 `/羽球 绑定 绑定码`；主持人在活动页生成群绑定码后在群内执行 `/羽球 关联 群绑定码`。

真实 WakeUp 与首个场馆网站的联调输入、限制与验收状态见 `docs/integrations/`。

