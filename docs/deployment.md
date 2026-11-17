# 服务器部署

适用单台 Linux 服务器，Docker Engine 与 Docker Compose v2 或更新版本。建议至少 2 GB 内存用于构建。应用为单 worker + SQLite，不能直接横向扩容多个副本。镜像同时构建 React 和 Python 服务；服务器不必另外安装 Node、Python 运行环境。初始化配置脚本可使用服务器 Python 3，也可手工复制模板。

## 1. 解压与配置

上传 `release/shuttleup-server.tar.gz` 和校验文件到服务器。不要上传本机开发 `.env` 作为生产配置。

```bash
sha256sum -c shuttleup-server.tar.gz.sha256
tar -xzf shuttleup-server.tar.gz
cd shuttleup
python3 scripts/init-env.py
nano .env
```

脚本只创建新 `.env`，不会覆盖现有文件，生成随机 APP_SECRET 和 Bot token；不会显示密钥。没有 Python 3 时可 `cp .env.example .env; chmod 600 .env`，再用 `openssl rand -hex 32` 分别生成两个随机密钥并填入。

必须填写：

| 配置 | 填法 |
| --- | --- |
| APP_BASE_URL | 用户实际访问地址，如 `https://ball.example.com`，不带末尾 `/` |
| SESSION_COOKIE_SECURE | HTTPS 使用 `true`；仅通过 SSH 隧道临时测试 HTTP 时设为 `false` |
| SMTP_HOST / SMTP_PORT / SMTP_SECURITY | 沿用邮件服务配置，如 QQ SMTP 的 SSL 465 |
| SMTP_USERNAME / SMTP_FROM / SMTP_PASSWORD | 发件邮箱、发件地址、邮箱授权码；密码含 `$`、`#` 等字符时用单引号包住 |
| BOOTSTRAP_ADMIN_EMAIL | 取消注释并填你指定的管理员邮箱，不能为空字符串 |

`APP_SECRET` 上线后保持稳定，否则会使邀请码、验证码等失效。数据库在 Docker 卷 `/data`，Compose 固定了正确的数据库地址。所有 `.env` 参数都会传入容器，SMTP 和管理员设置不再遗漏。修改配置后执行 `docker compose up -d --force-recreate`，仅 `restart` 不会重新注入环境变量。

## 2A. 已有 Nginx / 宝塔 / 其他 HTTPS 代理

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app
curl -f http://127.0.0.1:8000/readyz
```

上游配置为 `http://127.0.0.1:8000`，示例见 `deploy/nginx.conf.example`。应用端口仅绑定服务器回环地址，不需要放行 8000 公网端口。可通过 APP_PORT 改端口，同时修改反向代理上游。

Docker 桥接网络中，宿主机代理的来源通常是网络网关，不一定为 127.0.0.1。用 `docker inspect $(docker compose ps -q app) --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'` 查看网关，将其填入 FORWARDED_ALLOW_IPS 并重新创建容器。只信任实际代理地址。

## 2B. 没有代理：自动 HTTPS

将域名 A/AAAA 解析到服务器；若没有可用 IPv6，不要设置 AAAA。放行 TCP 80、443；UDP 443 可选。确保没有其他服务占用这些端口。在 `.env` 添加：

```dotenv
SITE_DOMAIN=ball.example.com
ACME_EMAIL=owner@example.com
APP_BASE_URL=https://ball.example.com
SESSION_COOKIE_SECURE=true
```

```bash
docker compose -f compose.yaml -f compose.https.yaml up -d --build
docker compose -f compose.yaml -f compose.https.yaml ps
docker compose -f compose.yaml -f compose.https.yaml logs --tail=100 caddy
```

Caddy 会申请和续期证书，证书保存在独立卷中，SSE 关闭缓冲。此模式中应用仅信任 Caddy 的容器地址。默认网络 `172.30.82.0/24` 如与服务器网络冲突，应同时调整覆盖文件中的子网、两个容器 IP 和 FORWARDED_ALLOW_IPS。

**此模式后续所有 Compose 命令都带两个 `-f` 参数**，或者先 `export COMPOSE_FILE=compose.yaml:compose.https.yaml`，再使用本文简写命令，包括备份脚本。

WakeUp 课表分享已内置真实协议，无需设置 WAKEUP_SHARE_ENDPOINT。登录后在「我的时间」粘贴分享文案，预览并确认；分享通常只有 30 分钟有效，时间设置错误会明确提示并拒绝导入。

## 3. 管理员和验收

用 BOOTSTRAP_ADMIN_EMAIL 指定邮箱在网页完成验证码注册后自动成为管理员。该设置不会给已存在账号追授权限；迁移已有账号时保留原来的管理员角色。管理员可通过侧栏「场馆管理」添加场馆。

无邮件服务时，可在服务器交互创建管理员：`docker compose exec app shuttleup admin create`。密码在终端隐藏输入；这是服务器维护入口，网页仍禁用用户名注册。

验收：打开 HTTPS 页面、注册和重新登录、发起活动、填写空闲时间、另一设备修改后观察实时提示；确认邮件可达。`/readyz` 仅说明应用和数据库可用，不代表 SMTP 或场馆外部服务已经联通。

AstrBot 插件在 `plugins/astrbot_plugin_shuttleup`，将 base_url 设为 APP_BASE_URL，api_token 使用服务器的 ASTRBOT_MAIN_TOKEN。

## 4. 更新与备份

```bash
sh scripts/backup.sh
# 在保留 .env 和数据卷的前提下更新源代码，然后：
docker compose up -d --build
docker compose ps
```

备份使用 SQLite backup API，存入服务器 `backups/`，同时在数据卷保留一份。另存副本到你控制的其他存储。备份含账号、活动和可能的私有场馆配置，不能提交 Git。`.env`、私有扩展和凭据文件需另行安全备份；数据库备份不包含它们。

**不要执行 `docker compose down -v`**，这会删除持久数据卷。升级前保留旧部署包和数据库备份；数据库迁移后不能只换回旧镜像来保证回滚。

## 5. 导入现有数据 / 恢复备份

先在原机器使用 `shuttleup backup` 导出数据库，不直接复制运行中的 `.db` 文件。上传备份后，停止 app，再导入：

```bash
docker compose stop app
docker compose run --rm -T --no-deps --entrypoint python app scripts/restore-database.py < ./backups/your-backup.db
```

导入脚本先检查完整性，保留替换前的数据库及 WAL 文件。对于本项目开发环境 `create_all` 创建、没有 Alembic 记录的现有数据库，还需执行：

```bash
docker compose run --rm --no-deps --entrypoint python app scripts/adopt-database.py
```

该命令仅在结构与本版本完全一致时补齐版本记录，并先保留备份。已有 Alembic 记录的备份跳过此步。结构不一致会拒绝标记，必须先在副本中处理迁移，不能强行 `stamp head`。最后启动并核对数据：

```bash
docker compose up -d
curl -f http://127.0.0.1:8000/readyz
```

## 6. 私有场馆扩展

按项目约定，涉及特定网站的代码、参数及登录文件均在忽略目录中，**通用部署包不包含它们**，全新部署不会自动出现本机的专属场馆查询功能。

要迁移这些功能，需要另行将自己的 `.local/` 扩展部署到服务器，挂载到容器 `/app/.local`，安装扩展自己的依赖，并按其说明调整容器内的凭据路径。扩展文件、参数和维护脚本继续留在忽略目录，不要添加到公共镜像或 Git。登录更新依赖本机桌面的扩展不能在无桌面服务器里直接弹出窗口；应按该扩展的私有说明在桌面完成登录后安全同步凭据。

容器用户 UID 为 10001，挂载数据应允许该用户读写；扩展代码可只读挂载。私有集成另行配置完毕后，需要实测查询和登录续期，不能仅以应用健康检查作为完成标准。

## 7. 生成部署包

开发机运行 `python3 scripts/package-release.py`。生成源码包与 SHA-256 校验文件，包含当前未提交但已完成的应用代码；排除 `.env`、数据库、`.local`、本机依赖和构建缓存。包中不含预构建镜像，服务器构建需要访问 npm、Python 包源和 Docker 镜像仓库。
