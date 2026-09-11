# ShuttleUp · 系统设计与实现规格

版本：1.0 · 2026-09-11  
规范性配套：`01-PRD.md`。本文是实现约定，字段、金额、状态与接口均以本文为准。  
目标：单机轻量部署、手机优先、美观、模块边界清楚，按纵向功能切片持续交付。

## 1. 技术决策

### 1.1 一套代码、一个运行服务

采用 **FastAPI + Vue 3 / TypeScript + SQLite** 的模块化单体。前端经 Vite 构建为静态文件，按需导入并拆分路由包，由 FastAPI 同域提供；生产环境只运行一个 Python 服务和一个 SQLite 数据目录。AstrBot 插件安装到用户已有 Bot 中，调用该服务。

```text
浏览器 ── REST 写入 / 查询 + SSE 更新 ─┐
                                      │
AstrBot 插件 ── Bot API / 通知长轮询 ───┤ FastAPI 单进程
                                      │  ├─ 身份、活动、时间、订场、账务
场馆网站 ←── Provider 定时查询 ─────────┤  ├─ 外部适配器与轻量后台循环
WakeUp   ←── 分享导入适配器 ────────────┘  └─ SQLite + 静态前端
```

后端业务用同步 SQLAlchemy 2 会话与短事务，HTTP 来源查询用 `httpx.AsyncClient`。后台循环在 FastAPI lifespan 中启动和关闭；这是 FastAPI 官方支持的资源生命周期入口。[T1] 普通同步路由在线程池内执行，异步后台任务通过 `asyncio.to_thread` 调用同步数据库服务，避免阻塞 SSE。

SSE 只负责服务端到浏览器的变更通知，客户端操作仍用 HTTP。浏览器原生 EventSource 提供事件 ID 与重连机制，不需要为单向同步增加 WebSocket 协议和客户端依赖。[T2]

### 1.2 依赖与约束

| 部分 | 选择 |
|---|---|
| Python | 3.12；运行镜像检验实际 SQLite 库版本 |
| Web | FastAPI、Uvicorn、Pydantic 2 |
| 数据 | SQLAlchemy 2、Alembic、SQLite WAL |
| 网络、认证 | httpx、argon2-cffi |
| 前端 | Vue 3 Composition API、TypeScript、Vue Router、Vite；按需打包 [T7] |
| 样式 | 原生 CSS 变量 + scoped CSS，按需 SVG 图标 |
| 测试 | pytest、httpx 测试客户端、Vitest、Playwright E2E |
| 依赖锁 | `uv.lock`、`package-lock.json`；生产与 CI 使用锁文件 |

不引入 Redis、Celery、消息队列、单独 Node 服务、微服务或全套后台 UI 框架。时间表用 CSS Grid 和本项目组件实现。Playwright 是开发测试依赖；仅当某个真实网站确实必须执行浏览器脚本时，才为该 Provider 单独增加可选运行依赖。

SQLite 开启 `foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout=5000`、`synchronous=FULL`。WAL 允许读写并行，但同一时刻仍只有一个写者，因此事务内不做网络请求。[T3] 使用本机数据卷，生产默认一个 Uvicorn worker。SQLite 采用 3.51.3 或更高的受支持版本，以包含官方记录的 WAL-reset 修复；镜像构建时实际检查 `sqlite3.sqlite_version`，不能仅依据 Python 版本推断。[T3]

### 1.3 扩展点只放在真正变化的位置

外部课表由 `ScheduleImporter` 适配；外部场地由 `VenueProvider` 适配；Bot 通过独立版本化 HTTP 契约接入。候选排序和分摊是可独立测试的纯函数。新场馆只增加 Provider 和配置，新 Bot 只增加适配插件，不修改活动和账务表结构。

后端模块之间调用明确的服务函数，不为每一张表建立抽象 Repository 基类，也不做动态插件市场。SQLAlchemy 模型不进入外部 Provider，HTTP Request 不进入纯算法。

## 2. 项目结构与现有骨架迁移

```text
shuttleup/
├── pyproject.toml, uv.lock
├── Dockerfile, compose.yaml, .env.example
├── backend/
│   ├── shuttleup/
│   │   ├── app.py, config.py, db.py, cli.py
│   │   ├── auth/           # models, schemas, service, routes
│   │   ├── activities/     # 活动、成员、方案、订场
│   │   ├── availability/   # 规则、课程导入、纯区间算法
│   │   ├── venues/         # 查询协调、快照、Provider
│   │   ├── billing/        # 费用、纯分摊、账单、付款
│   │   ├── integrations/   # bot_api、身份绑定、通知
│   │   └── realtime/       # events、SSE、后台循环
│   ├── migrations/
│   └── tests/              # unit、integration、fixtures
├── frontend/
│   ├── src/
│   │   ├── api/            # fetch、OpenAPI 生成类型
│   │   ├── components/     # 基础组件与少量领域组件
│   │   ├── composables/    # session、activity、events
│   │   ├── pages/
│   │   └── styles/         # tokens.css、base.css
│   └── tests/
├── plugins/astrbot_plugin_shuttleup/
│   ├── main.py, metadata.yaml, _conf_schema.json
│   └── tests/
├── docs/                   # 本文、PRD、开发进度、来源协议说明
└── scripts/                # 数据导入、验收种子、备份命令入口
```

模块初始以 `models.py / schemas.py / service.py / routes.py` 组织，文件复杂后再拆分，不预建大量空目录。根目录现有 `backend/shuttleup/domain.py`、`availability.py`、`settlement.py` 是早期骨架，保留有价值的测试并迁移，不因已有枚举而沿用过度串联的状态机。

已检查的骨架需要调整：活动状态分离账务状态；金额由 Decimal 对象改为整数分；分配规则不再“每人四舍五入后把全部漂移丢给一个人”。后者在 2 分钱四人分摊时可能让一人承担负数，新算法固定为商与余数分配。原先四个单元测试不能代替完整产品验收。更新 README 与旧 `docs/architecture.md`，避免存在两套相冲突的规格。

## 3. 通用数据约定

实体主键为 UUID 字符串，便于 SQLite 与未来其他关系库共用；用户可见短号为独立唯一字段，不能用于授权。事件序号使用数据库自增整数。所有 UTC 时刻在持久层统一保存为 Unix 毫秒 `INTEGER`，API 输出带偏移的 RFC 3339 字符串。日期使用 `YYYY-MM-DD`，当地钟点使用 `HH:mm`；周期规则另存 IANA `timezone`。

时间区间统一为左闭右开 `[start,end)`，必须 `end > start`。金额字段后缀 `_cents`，类型为有符号整数；单笔支出上限 100,000,000 分，正向支出必须大于零，退款小于零。API 不用 JSON 浮点数表示金额。零价是合法报价，但无实付不生成支出。

可编辑记录带 `created_at`、`updated_at`、`created_by`、`version`。以下表中省略这些通用字段；快照表只追加不覆盖，事件表不使用业务版本号。外键默认限制删除，活动、费用以状态或 `voided_at` 保留业务历史。

## 4. 数据模型

下列是必须落实到迁移中的逻辑表定义。JSON 仅用于小型配置和不可变快照；权限、归属、状态、时间索引和金额保留独立列。

### 4.1 用户与设置

| 表 | 字段与约束 |
|---|---|
| `users` | `id PK`、`display_name`、`username NULL UNIQUE`、`password_hash NULL`、`is_admin BOOL`、`timezone`、`availability_revision INT DEFAULT 0`、`disabled_at NULL`。用户名保存规范化小写值；访客没有用户名和密码 |
| `sessions` | `id PK`、`token_hash UNIQUE`、`csrf_hash`、`user_id FK`、`expires_at`。会话只存 token 的哈希 |
| `app_settings` | `id PK CHECK id=1`、`timezone`、`court_hourly_cents NULL`、`shuttle_unit_cents NULL`、`shuttle_label NULL`、`guest_join_enabled BOOL` |
| `one_time_tokens` | `id PK`、`token_hash UNIQUE`、`purpose`、`user_id FK NULL`、`activity_id FK NULL`、`participant_id FK NULL`、`expires_at`、`consumed_at NULL`。purpose=`bot_bind/group_bind/participant_claim` |

访客升级只为同一 `users.id` 设置凭据。主持人补记的临时球友也创建无会话的访客用户，因此所有费用始终关联到 `participant_id`，不需要第二套“纯文本债务人”。认领通过一次性 token 将这位临时球友的活动参与记录绑定到当前用户，participant_id 保持不变；同活动已有该用户时返回 MEMBER_ALREADY_EXISTS，由主持人在出账前整理重复档案，不自动合并已发布账单里的身份。

### 4.2 时间规则

| 表 | 字段与约束 |
|---|---|
| `schedule_imports` | `id PK`、`user_id FK`、`provider_key`、`label`、`term_start_date`、`term_end_date`、`timezone`、`payload_hash`、`occurrence_count`、`imported_at`；`UNIQUE(user_id,provider_key,label)`，存导入元数据，不保存口令 |
| `availability_rules` | `id PK`、`user_id FK`、`activity_id FK NULL`、`import_id FK NULL`、`origin_plan_id FK NULL`、`source`、`state`、`kind`、`start_at/end_at NULL`、`recurrence JSON NULL`、`edit_seq INT`。`kind=once` 必须有区间；`kind=weekly` 必须有 recurrence；`source=activity` 必须有 activity_id |

`source` 枚举为 `baseline/course/weekly/one_off/activity`，优先级对应 PRD 的 0/10/20/30/40。course 只能由导入服务生成且 state=busy；外部请求不能自带 priority 或替他人设置规则。课程导入保存展开后的实际区间，kind=once；用户的基础可约窗与每周设置保存 kind=weekly。导入生效的一次事务同时替换旧课程规则和增加 `availability_revision`。

`edit_seq` 使用用户的 `availability_revision`：每次保存一批规则先递增一次 revision，同一批中不允许有互相矛盾的重叠规则；比较优先级相同的规则时按 `edit_seq`，无需依赖毫秒时间戳打破并发并列。

```json
{
  "weekdays": [1, 3, 5],
  "start_time": "18:00",
  "end_time": "22:00",
  "valid_from": "2026-09-07",
  "valid_until": "2027-01-24",
  "timezone": "Asia/Shanghai"
}
```

星期一为 1，星期日为 7；`valid_until` 日期包含在内。跨午夜规则在应用层拆成两条。索引为 `(user_id,activity_id)`、`(user_id,start_at,end_at)`、`import_id`。

### 4.3 活动与订单

| 表 | 字段与约束 |
|---|---|
| `activities` | `id PK`、`short_code UNIQUE`、`title`、`host_user_id FK`、`status`、`timezone`、`date_from/date_to`、`daily_windows JSON`、`duration_minutes`、`min_players/max_players`、`court_count`、`venue_preferences JSON`、`decision_deadline NULL`、`invite_nonce`、`invite_token_hash UNIQUE NULL`、`invite_enabled`、`price_defaults JSON`、`current_plan_id FK NULL`、`billing_status DEFAULT draft`、`bill_generation INT DEFAULT 0`、`current_bill_id FK NULL`、`archived_at NULL`、`cancel_reason NULL` |
| `participants` | `id PK`、`activity_id FK`、`user_id FK`、`display_name`、`join_order INT`、`membership=active/left/removed`、`required BOOL`、`rsvp=pending/yes/no`、`rsvp_plan_id FK NULL`、`attendance=unknown/present/absent`、`attendance_verified BOOL`；`UNIQUE(activity_id,user_id)`、`UNIQUE(activity_id,join_order)` |
| `activity_plans` | `id PK`、`activity_id FK`、`plan_no`、`starts_at/ends_at`、`venue_id FK`、`court_ids JSON`、`roster_participant_ids JSON`、`candidate_fingerprint`、`snapshot JSON`、`selected_by FK`；`UNIQUE(activity_id,plan_no)`；不可变 |
| `bookings` | `id PK`、`activity_id FK`、`plan_id FK`、`venue_id FK`、`court_ids JSON`、`starts_at/ends_at`、`external_order_no NULL`、`booker_participant_id FK`、`status=confirmed/cancelled`、`quoted_total_cents NULL`、`paid_total_cents DEFAULT 0`、`payer_participant_id FK NULL`、`note NULL` |

人数约束：`2 <= min_players <= max_players <= 30`；场数 1–8；时长 30–360 分钟且为 15 分钟整数倍。date_to 包含在搜索日期范围中，总跨度不超过 14 天。daily_windows 是星期与钟点数组，格式与 recurrence 的星期/钟点部分一致。venue_preferences 为不重复的场馆 ID 有序数组。

`price_defaults` 保存 `global_court_hourly_cents`、`venue_hourly_cents`（venue_id→费率）、`court_hourly_override_cents`、`shuttle_unit_cents`、`shuttle_label`。估算某馆时依次取活动显式 override、该馆快照费率、全局快照费率；后续管理员调价不影响此快照。活动全局 `version` 覆盖配置、成员与计划等可协作数据的变更。候选不建数据库表：由活动、时间规则、来源快照即时生成；只有选定结果存 `activity_plans`。

同一订单的每次实际付款记录为关联 `booking_id` 的正向费用；`bookings.paid_total_cents` 由这些费用计算或事务内维护，不由客户端单独随意修改。分次付款可产生多笔支出，确保实际垫付人准确。可选订单号在同场馆、非空时建立唯一约束，人工无订单号允许留空。

### 4.4 场馆与来源

| 表 | 字段与约束 |
|---|---|
| `provider_configs` | `id PK`、`key UNIQUE`、`adapter_key`、`label`、`config JSON`、`credential_env NULL`、`min_poll_seconds`、`min_request_interval_seconds`、`fresh_for_seconds`、`enabled BOOL`。真实凭据从命名环境变量读取，不返回浏览器 |
| `venues` | `id PK`、`provider_id FK`、`external_venue_id`、`name`、`address`、`timezone`、`booking_url`、`hourly_rate_cents NULL`、`enabled BOOL`；`UNIQUE(provider_id,external_venue_id)` |
| `venue_snapshots` | `id PK`、`venue_id FK`、`local_date`、`revision INT`、`content_hash`、`slots JSON`、`coverage JSON`、`last_success_at NULL`、`last_attempt_at`、`next_poll_at`、`last_error_code NULL`、`reported_stale_at NULL`；`UNIQUE(venue_id,local_date)` |

一张快照保存一天少量时段，以统一 JSON 契约描述，适合整日查询及连续性计算。新快照只替换已声明完整覆盖的查询窗口；来源只返回部分信息时，不删除其他窗口。重复抓取内容相同只更新查询时刻，不增加 `revision`；达到过期时间也必须触发一次候选失效通知。

### 4.5 费用、账单与付款

| 表 | 字段与约束 |
|---|---|
| `expenses` | `id PK`、`short_code UNIQUE`、`activity_id FK`、`kind=venue/shuttle/extra/refund`、`description`、`amount_cents`、`payer_participant_id FK`、`split_mode=equal/exact`、`split_scope=attendees/selected`、`quantity NULL`、`unit_price_cents NULL`、`booking_id FK NULL`、`refund_of_id FK NULL`、`voided_at NULL` |
| `expense_shares` | `id PK`、`expense_id FK`、`participant_id FK`、`exact_amount_cents NULL`；`UNIQUE(expense_id,participant_id)`。equal 只记录范围，exact 保存明确金额；动态 attendees 的草稿暂不写行 |
| `bill_revisions` | `id PK`、`activity_id FK`、`revision_no`、`source_generation`、`snapshot JSON`、`total_cents`、`published_by FK`、`published_at`；`UNIQUE(activity_id,revision_no)`；不可变 |
| `payment_claims` | `id PK`、`short_code UNIQUE`、`activity_id FK`、`bill_revision_id FK`、`transfer_id`、`from_participant_id FK`、`to_participant_id FK`、`amount_cents > 0`、`status=claimed/confirmed/rejected/withdrawn`、`claimed_at`、`confirmed_at NULL`、`resolved_by_user_id FK NULL` |

`transfer_id` 在 bill snapshot 内唯一，用 `(bill_revision_id,transfer_id)` 定位。它不是另一个可修改的总账表。每条转账指令同时最多有一个未解决的 claimed 记录；对该 pair 建立条件唯一索引。所有确认过的 payment_claims 在后续修订中继续参与余额计算。

所有 payer、share、from、to 必须属于同一 activity，不能仅靠存在某个 UUID 就接受。`bill_generation` 在费用、到场核对、承担范围变更时递增；账单预览携带此 generation，发布时核对。发布后费用不可直接修改，先调用 reopen。

### 4.6 Bot、事件与幂等

| 表 | 字段与约束 |
|---|---|
| `bot_identities` | `id PK`、`bot_key`、`platform_id`、`sender_id`、`user_id FK`、`private_umo NULL`；`UNIQUE(bot_key,platform_id,sender_id)` |
| `bot_contexts` | `id PK`、`bot_key`、`umo`、`label`、`current_activity_id FK NULL`；`UNIQUE(bot_key,umo)` |
| `bot_activity_links` | `id PK`、`context_id FK`、`activity_id FK`、`notifications_enabled BOOL`；`UNIQUE(context_id,activity_id)` |
| `events` | `seq INTEGER PK AUTOINCREMENT`、`event_id UNIQUE`、`type`、`activity_id FK NULL`、`owner_user_id FK NULL`、`actor_user_id FK NULL`、`resource_version INT`、`payload JSON`、`occurred_at`、`processed_at NULL` |
| `notifications` | `id PK`、`event_seq FK NULL`、`dedupe_key UNIQUE`、`target_type=user/bot_context`、`target_user_id FK NULL`、`target_context_id FK NULL`、`payload JSON`、`state=pending/leased/sent/failed`、`available_at`、`lease_until NULL`、`lease_token_hash NULL`、`attempts`、`delivered_at NULL`、`read_at NULL` |
| `operation_keys` | `id PK`、`scope`、`key`、`request_hash`、`response_status`、`response JSON`、`expires_at`；`UNIQUE(scope,key)` |

索引重点：活动主持人与状态、成员用户与活动、费用 activity_id、付款 activity_id/status、events(seq)/processed_at、notifications(state,available_at)。所有状态变更和对应事件在同一数据库事务提交。事件是变更通知和轻量审计，不是 event-sourcing；当前状态仍由正常业务表读取。

## 5. 身份、请求与事务

### 5.1 Web 身份

服务端生成 256-bit 随机会话 token，Cookie 为 HttpOnly、SameSite=Lax，生产启用 Secure。有效期 30 天，活跃访问续期。用户名 3–32 个字母、数字或下划线，密码至少 10 个字符，使用 Argon2id。邀请为可重新生成的高熵能力链接：创建时生成 128-bit invite_nonce，token 为 `base64url(HMAC-SHA256(APP_SECRET,"invite:" + activity_id + ":" + invite_nonce))`，数据库存 nonce 和 token 哈希。主持人读取邀请时服务端可重建同一链接；rotate 更换 nonce 并更新哈希。

会话 Cookie 命名为 shuttleup_session，Path=/。CSRF token 由 `base64url(HMAC-SHA256(APP_SECRET,"csrf:" + raw_session_cookie))` 派生，服务端可在读取当前 Cookie 后重建，不需要反查哈希原文。

`GET /api/v1/session` 返回当前用户与当前会话 CSRF token；写请求校验 `X-CSRF-Token` 和同源 Origin。创建会话的注册／访客／登录请求校验 Origin。Web 页面不保存 Bearer token 到 localStorage。Bot 使用独立服务 token 和独立路由，不复用浏览器 Cookie。

首次管理员由 CLI `shuttleup admin create` 创建；全局设置只接受管理员操作。主持人身份通过 `activities.host_user_id` 查询。所有资源权限在服务函数中判断，Web 与 Bot 调用同一函数。已退出／被移除成员仍可以访问本人的账款投影和涉及本人的付款接口；这些权限不重新开放整场活动、成员时间表或活动 SSE。

### 5.2 修改版本与幂等

客户端的可编辑表单提交 `expected_version`。服务端执行条件更新，版本不一致返回 409 和当前版本，前端刷新受影响表单并保留用户输入。不引入通用 CRDT 或协同文本编辑。

费用创建、订单付款登记、账单发布、付款声明和确认收款携带 `Idempotency-Key`。同一 scope/key 同请求返回原结果；同 key 不同内容返回 409。scope 包含 actor_id 与操作类型。Bot 使用平台 message_id 派生 key，避免平台重发产生双重支出。幂等结果与业务写入在一个事务提交，保留 30 天。

事务只包含：权限、版本、业务写入、事件和必要通知记录。课表拉取、场馆查询与 IM 投递都在事务之外执行。同步 SQLAlchemy Session 不能跨线程传递；进入线程时创建、退出时关闭。

## 6. 状态转换和业务服务

### 6.1 活动状态

| 服务函数 | 起点 → 终点 | 前置条件与写入 |
|---|---|---|
| `create_activity` | 无 → collecting | 创建 host participant、价格快照、邀请 token |
| `select_plan` | collecting/booking → booking | 正常候选仍有效；名单满足人数与核心成员；新增 plan，重置计划相关 rsvp |
| `clear_plan` | booking → collecting | 当前计划没有仍有效的订单；移除 current_plan 指向 |
| `record_booking` | booking → booking/confirmed | 保存真实订单；覆盖所需完整时段和固定场数后 confirmed |
| `begin_reschedule` | confirmed → booking/confirmed | 旧订单逐笔标记取消或明确迁移到新计划；新增计划、重置 rsvp |
| `finish_activity` | confirmed → finished | 主持人结束；保留未核对到场项 |
| `cancel_activity` | collecting/booking/confirmed → cancelled | 保存原因；不改财务事实 |
| `archive_activity` | finished/cancelled，不变 | billing_status=settled；设置 archived_at |

对“迁移旧订单”的操作，只允许订单内容仍然覆盖新计划，例如仅更换名单；时间或场馆不一致时必须标记旧订单已处理并另外登记新订单。取消订单状态与退款入账分开，不能假设取消必然全额退款。

迁移后的订单若已完整覆盖新计划，可在同一事务直接恢复 confirmed。回应 yes 生成带 origin_plan_id 的 activity 规则；回应 no、替换计划时清除此类自动规则并增加对应用户时间版本，不删除其手工覆盖。

有有效订单时重新选择时间必须走 reschedule，不能通过 select_plan 绕过订单处理。已结束活动不重新开球，复制创建新活动。

### 6.2 账单状态

| 服务函数 | 起点 → 终点 | 约束 |
|---|---|---|
| `create/update/void_expense` | draft → draft | 按成员／主持人权限；递增 bill_generation |
| `publish_bill` | draft → issued/settled | 活动 finished/cancelled；到场已核对；费用分摊完整；生成快照；无剩余转账则 settled |
| `claim_payment` | issued，不变 | 当前版本的付款人；金额不超过剩余应付；一个 pending claim |
| `confirm_payment` | issued → issued/settled | 只能由收款人确认；全体余额为零则 settled |
| `reopen_bill` | issued/settled → draft | 主持人；没有 claimed 待处理记录；保留所有 confirmed 转账 |

修改全局费率不触发已有活动 bill_generation。普通时间变更也不触发财务重算。只对真正影响账款的到场、费用和分摊操作更新账务版本。

## 7. 时间引擎与 WakeUp

### 7.1 对外纯函数

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AvailabilityState = Literal["free", "busy", "unknown"]

@dataclass(frozen=True)
class Interval:
    start: datetime  # aware datetime
    end: datetime

@dataclass(frozen=True)
class ResolvedSegment:
    span: Interval
    state: AvailabilityState
    source: str | None

def resolve_availability(rules, query: Interval, timezone: str) -> list[ResolvedSegment]:
    """把规则展开、裁剪、覆盖并合并，完整覆盖 query，包含 unknown。"""
    ...

def summarize_window(resolved: list[ResolvedSegment], query: Interval) -> AvailabilityState:
    """全程 free 才是 free；含 busy 则 busy；其余是 unknown。"""
    ...
```

输入规则必须已经按 user_id 和本次 activity_id 过滤，其他活动的局部覆盖不进入计算。返回 `source` 仅用于本人解释视图；共享 DTO 不返回私人规则 ID、课程名称或来源细节。

### 7.2 区间解析算法

先将 weekly 规则在查询的当地日期范围内展开为实际 UTC 区间，与 once 区间一起裁剪到 query。收集 query 起止和所有规则起止边界，排序去重。对每个相邻边界区间选择覆盖它的最高 `(source_priority, edit_seq)` 规则，无规则则 unknown。最后合并状态和来源相同的相邻区间。

首版成员不超过 30、查询不超过 14 天，直接边界扫描便于验证。复杂度主要由每用户几百个规则决定，不按秒枚举，不把 15 分钟 UI 栅格当成计算精度。跨天区间正确切分；比较和求交统一使用 UTC 时刻，周期展开在规则自己的时区内完成。

周次由学期首周的星期一计算：`week_index = floor((local_date - term_start_monday).days / 7) + 1`。单双周先转为明确 `weeks` 数组。遇到有夏令时的配置，具体日期输入要求提供有效偏移；周期产生不存在的当地时间时跳过该次并在本人规则预览提示，重复钟点固定选择 `fold=0`。默认上海时区不涉及这一转换。

### 7.3 WakeUp 适配契约

```python
class ScheduleImporter(Protocol):
    key: str

    async def fetch(self, share_text: str) -> bytes:
        """仅从该适配器的固定可信来源获取分享内容。"""
        ...

    def normalize(self, payload: bytes) -> "NormalizedSchedule":
        """把上游格式转换为已确定日期和节次的业务结构。"""
        ...
```

内部标准化对象示例，**这是 ShuttleUp 的契约，不声称是 WakeUp 原始返回格式**：

```json
{
  "provider_key": "wakeup",
  "label": "2026秋季课表",
  "timezone": "Asia/Shanghai",
  "term_start_monday": "2026-09-07",
  "term_end_date": "2027-01-24",
  "periods": [
    {"index": 1, "start": "08:00", "end": "08:45"},
    {"index": 2, "start": "08:55", "end": "09:40"}
  ],
  "lessons": [
    {"external_key": "course-1", "preview_title": "示例课程", "weekday": 1,
     "weeks": [1, 3, 5], "period_indices": [1, 2]}
  ],
  "dated_occurrences": []
}
```

规范化流程：提取有效口令 → 获取真实分享内容 → 解析学期元数据、节次表和课程周次 → 转成明确 occurrence → 预览 → 确认导入。每个节次先产生准确的繁忙区间，相邻有间隔的节次不自动把间隔吃掉；与已有业务时间规则合并由时间引擎完成。

预览对象保存在当前进程中，以 `(user_id,preview_id)` 索引，有效期 10 分钟；其中可短暂保留课名供本人核对。确认后仅写入课程繁忙区间与导入元数据，删除预览，不保存原分享口令或整个原始响应。用户设置的 baseline 与导入可以在同一提交中保存。

截至本次核对，官方用户文档确认了分享口令导入，但没有在所查资料中提供可作为稳定契约的公开开发者接口。实现真实适配器时，用有效口令确认当时的上游请求和响应，并记录到 `docs/integrations/wakeup-source.md`；脱敏响应进入测试 fixtures。不要把未经验证的 URL、请求头或字段名写成已完成接口。[T4]

验收必须包含奇数周、偶数周、不连续指定周、连续节次、午休间隔、明确日期调课，以及重导替换。真实口令取样后立即脱敏，不提交个人课程名称。

## 8. 场地 Provider、刷新与候选生成

### 8.1 Provider 协议

```python
from datetime import date
from typing import Protocol

class VenueProvider(Protocol):
    key: str

    async def list_venues(self) -> list["ExternalVenue"]:
        ...

    async def fetch_day(self, venue_external_id: str, local_date: date) -> "VenueDayResult":
        ...

    async def health(self) -> "ProviderHealth":
        ...
```

`ExternalVenue` 包含 external_venue_id、name、address、timezone、booking_url 和可空的 hourly_rate_cents；`ProviderHealth` 包含 status（ok/error/auth_required）、checked_at 和 message。

Provider 只返回数据，不写数据库、不发布通知、不决定活动状态。`ProviderRegistry` 是一个明确的 `adapter_key -> factory` 映射。配置和 HTTP client 从构造函数传入；新增适配器不修改调度器。

一次整日结果示例：

```json
{
  "schema_version": 1,
  "external_venue_id": "gym-a",
  "local_date": "2026-09-19",
  "timezone": "Asia/Shanghai",
  "fetched_at": "2026-09-18T12:00:00+08:00",
  "coverage": {
    "starts_at": "2026-09-19T08:00:00+08:00",
    "ends_at": "2026-09-19T22:00:00+08:00",
    "complete": true,
    "identity_mode": "court"
  },
  "slots": [
    {
      "external_slot_id": "c3-20260919-1800",
      "court_id": "c3",
      "court_name": "3号场",
      "starts_at": "2026-09-19T18:00:00+08:00",
      "ends_at": "2026-09-19T19:00:00+08:00",
      "status": "available",
      "price_cents": 6000,
      "remaining_count": 1,
      "release_at": null,
      "booking_url": "https://venue.example/booking"
    },
    {
      "external_slot_id": "c3-20260919-1900",
      "court_id": "c3",
      "court_name": "3号场",
      "starts_at": "2026-09-19T19:00:00+08:00",
      "ends_at": "2026-09-19T20:00:00+08:00",
      "status": "available",
      "price_cents": 6000,
      "remaining_count": 1,
      "release_at": null,
      "booking_url": "https://venue.example/booking"
    }
  ]
}
```

示例域名仅表示配置结构，不是已经接入的场馆。slot.status 为 `available/unavailable/not_released/unknown`。price_cents 是**一块场地购买整个 slot 的总价**，不是小时单价。所有时间必须带偏移；court_id 在同一场馆中稳定。不同报价套餐可以有不同 external_slot_id，不按行数增加球场数量。

聚合来源使用 `identity_mode=aggregate`、`court_id=null`、`remaining_count=N`。V1 将其显示为需核实余量，不推导具名连续球场。未返回的区间按 unknown 处理；如果上游语义能确定缺失即已售，适配器负责显式生成 unavailable，核心服务不猜测。

标准 JSON Provider 从管理员配置的固定 endpoint 读取上述契约；人工 Provider 使用相同模型提供编辑入口；真实站点 Provider 将它的 HTTP/HTML 数据转换为同一结果。来源地址由管理员配置并限制到具体域名，普通用户不能让服务器抓任意 URL。credential_env 仅允许读取以 VENUE_ 开头的配置项。普通登录态由运维提供，爬虫按站点允许的访问方式和频率查询，不实现验证码绕过。

### 8.2 调度与共享快照

后台每 2 秒检查有需要的 `(venue_id,local_date)`。需要查询的范围来自 collecting/booking 活动的候选场馆和日期；已确定、已结束和已取消活动不产生常驻查询。

一个 SSE 连接可带 `watch_activity_id` 标记当前可见活动。存在可见观看者时目标周期 30 秒，否则 120 秒，并与 `min_poll_seconds` 取较大值。同键只允许一个进行中的查询，多个活动共享；每个 Provider 的并发默认为 1，另用 min_request_interval_seconds 控制整个来源的请求间隔。排程优先最近活动日期，同一个过期查询键只保留一份待执行项，不积累追赶任务。

处理流程为：取需求 → 网络查询 → 验证标准响应 → 短事务更新快照 → 发布有意义的变更事件。`content_hash` 不包含 fetched_at；内容相同不增加快照 revision。每次成功查询清空 reported_stale_at。当前时间超过 `last_success_at + fresh_for_seconds` 且 reported_stale_at 为空时，事务设置该字段，后台产生一次 stale 变更，候选立即重算；时间流逝本身也是失效输入。

抓取错误只更新 last_attempt_at/error_code，保留 last_success_at 与旧 slots 供页面解释；旧 slots 失效后不能继续参与 verified 候选。异常只显示具体错误和刷新状态，不创建额外的“自动猜测余量”路径。

### 8.3 候选算法

函数输入为活动快照、成员解析后的忙闲区间、场馆快照和 `now`，输出 `Candidate[]`。核心算法不读取数据库，便于构造固定测试。

1. 过滤活动的日期范围和允许时间窗，排除已经开始的时段。候选 start 取来源可购买 slot 的起始边界；end=`start + duration`，并要求整个区间处在允许时间内。仅展示人的共同时间时才按 15 分钟网格列举起点。
2. 每位 active 成员用 summarize_window 判断全程 free/busy/unknown。保留完整 eligible 列表，不预先截断到 max_players。验证最低人数及核心成员。
3. 对每个具名球场，把 available slot 建成从 starts_at 到 ends_at 的有向边。`cover_court(court,start,end)` 寻找从 start 到 end 的连续路径，不能出现间隙、跨球场或超买一截时段。这样同时支持 30/60 分钟单元和不同报价套餐。
4. 同一球场多条路径时按“无未知价优先、总价低优先、slot_id 顺序”选择一条。时间边只向前，按时间排序做动态规划即可。已过期快照或 coverage 不完整的缺口不得作为 available 边。
5. 得到所有完整覆盖的球场，数量至少 court_count 才生成 verified 候选。默认选择已知总价优先、总价最低的 K 块；保留所有 court_options 供主持人查看。金额是每块选中路径的 slot 总价之和，有一个未知即 total_price_cents=null。
6. 用 PRD 的字典序排序：`(-min(eligible_count,max_players), venue_preference_index, price_is_unknown, known_total_price, starts_at, venue_id)`。同一时段同一场馆只保留一张候选卡，避免排列组合刷屏。

`candidate_fingerprint = hash(activity.version, venue_id, start, end, selected_courts_and_slot_ids)`，再提供碰撞检查后的短号。候选响应还携带用户 availability_revision 集合、来源 revision 和过期时刻，作为输入签名。成员修改时间时可以复用相同内容的短号，但每次 select_plan 都要基于**当前输入重新验证**，不盲信旧卡片的结果。

改约计算可把本活动已确认且尚未取消的订单作为“已拥有”的时间边，与外部可预约边组合；这些边只用于该活动，不写回网站余量，也不能供别的活动使用。

候选缓存仅在进程内，以活动 ID 和输入签名索引；到来源过期时刻自动失效。不保存“可用球场库存”，也不把选中候选当作网站锁场。

### 8.4 候选响应示例

```json
{
  "activity_version": 8,
  "generated_at": "2026-09-18T12:00:00+08:00",
  "candidates": [
    {
      "id": "cnd_6d21b6a9d83f",
      "short_code": "C7K2",
      "classification": "verified",
      "starts_at": "2026-09-19T18:00:00+08:00",
      "ends_at": "2026-09-19T20:00:00+08:00",
      "venue_id": "venue-a",
      "court_ids": ["c3"],
      "continuous_court_count": 1,
      "eligible_participant_ids": ["pa", "pb", "pc", "pd", "pe"],
      "unknown_participant_ids": [],
      "busy_participant_ids": [],
      "total_price_cents": 12000,
      "last_success_at": "2026-09-18T12:00:00+08:00",
      "fresh_until": "2026-09-18T12:01:30+08:00",
      "reason_codes": ["MIN_PLAYERS_MET", "REQUIRED_PLAYERS_FREE", "COURTS_CONTINUOUS"]
    }
  ],
  "other_windows": []
}
```

来源没有报价时可额外返回按本次费率快照计算的 estimated_total_cents，界面标“按默认费率估算”；total_price_cents 仍为 null，不能把估计价冒充已知报价参与排名。

示例 ID 为便于阅读的别名，实际实体 ID 为 UUID。`other_windows` 按同样字段结构附 `classification=people_only/needs_court_check/insufficient_players` 与 reason_codes；前端不可把它们渲染成 verified。

## 9. 账务算法与不可变账单

### 9.1 精确金额输入

浏览器金额输入保留字符串，按正则解析到分，例如 `"12.30" -> 1230`；不使用 `parseFloat(value) * 100`。后端只接收 amount_cents。场地时间单价换算可以使用 Decimal 在内部计算一次，最终按 ROUND_HALF_UP 转为整数分；持久化和分账只处理整数。

预计场地费：`round_half_up(hourly_cents * court_count * duration_minutes / 60)`。费用确认采用实际 amount_cents。球数量为正整数，`unit_price_cents * quantity`。成员更改品名或备注不改变金额，只有明确保存金额变更才递增账务 generation。

### 9.2 支出分配

均分算法对正费用 `M`、成员数 `N`，计算 `q,r = divmod(M,N)`。成员按 `(join_order,participant_id)` 排序，前 r 人承担 q+1 分，其余 q 分。结果不受数据库查询顺序或随机 UUID 的变化影响。

精确分摊直接接受每人整数分金额，要求全部非负、无重复成员且合计=M。同一笔费用的承担人允许包含未到场成员，但必须属于活动历史成员集合。动态 attendees 在出账时展开为已核对 present 的成员；若无人承担，主持人必须指定承担人，不能除以零或自动归给主持人。

退款保存负 amount_cents 和关联原费用。以原费用尚未退回给各承担人的金额作为权重，对本次退款绝对值按最大余数法分配，然后取负；余数相同按 join_order。每个人本次退款不超过其剩余承担额。多次退款使用剩余额度重新计算，所有退款累计不超过原费用。

原费用未发布过时，在记录退款前先固定其承担人和整数分结果，落为 exact/selected 的 expense_shares；原费用发布过则从最近快照固定原分配；已有退款关联的原费用不能单独修改金额、承担范围或作废，需连同关联退款一并更正。精确退款同样要求对每位成员不超过尚未退款额。收到商家退款的人填到该负费用的 payer 字段。

### 9.3 余额与转账计划

对成员 u 定义：

```text
outlay[u] = Σ amount_cents，其中 expense.payer = u（含负退款）
share[u]  = Σ 该成员每笔费用的已分配金额（含负退款份额）
sent[u]   = Σ 已确认的球友转账，from = u
received[u] = Σ 已确认的球友转账，to = u
balance[u] = outlay[u] - share[u] + sent[u] - received[u]
```

balance>0 还应收，balance<0 还应付。每次计算必须满足 `sum(balance)=0`、`sum(shares)=sum(expenses)`。声明付款但尚未确认的金额不进入 sent/received。

将债权人按 `(-balance,join_order,id)` 排序，将债务人按 `(-abs(balance),join_order,id)` 排序。双指针配对，每次转移两者剩余额度的较小值，一方清零就前进，直到完成。输出最多为非零余额人数减一条，不声称求得全局最少转账笔数。

纯函数：`allocate_expense(expense,participants)`、`calculate_balances(allocated_expenses,confirmed_payments)`、`simplify_transfers(balances)`；不读取 Session，也不修改付款状态。

### 9.4 发布快照

发布服务在同一事务核对 activity 状态、bill_generation 和权限，重新计算而不是接受前端提交的结算结果，然后保存：

```json
{
  "schema_version": 1,
  "currency": "CNY",
  "participant_snapshots": [
    {"id": "pa", "name": "A", "join_order": 1},
    {"id": "pb", "name": "B", "join_order": 2}
  ],
  "expense_snapshots": [
    {"id": "ex1", "amount_cents": 12000, "payer_participant_id": "pa",
     "allocations": [{"participant_id": "pa", "amount_cents": 6000},
                     {"participant_id": "pb", "amount_cents": 6000}]}
  ],
  "confirmed_payment_ids_at_publish": [],
  "balances_at_publish": {"pa": 6000, "pb": -6000},
  "transfers": [
    {"id": "tr1", "short_code": "T4J8", "from_participant_id": "pb",
     "to_participant_id": "pa", "amount_cents": 6000}
  ]
}
```

每个账单版本保存当时完整费用分配、昵称快照、已确认付款 ID 集合和初始剩余余额。这样修改昵称、全局费率或未来课表不改变旧账单含义。

同一版本的转账指令保持不变；其剩余额度等于原指令金额减该指令已 confirmed 的付款总额。一次最多一个 claimed 防止重复点击抢占同一份余额。确认接口在事务中再次核对余额，不能累计超收。

### 9.5 修订和退款例子

reopen 将 billing_status 改为 draft，保留所有历史快照和 confirmed payment_claims。新版本发布时用最新费用和**全部已确认的历史转账**重新计算 balance，重新生成只针对剩余净额的转账指令。旧版本只读，不能再创建付款声明。

固定退款测试：A 垫付 120 元，四人各承担 30 元，B/C/D 已各给 A 30 元且确认。之后场馆向 A 退 40 元，四人各减 10 元承担。重出账后 A 应分别退给 B/C/D 各 10 元；不能再次向 B/C/D 收费，也不能把 A 收到的 40 元全部留给 A。

取消活动以相同账务模型运行。不另做“取消退款子系统”，不把活动状态用作删除费用的触发器。

## 10. HTTP API 契约

### 10.1 通用约定

Web 前缀 `/api/v1`；Bot 前缀 `/bot/v1`。成功直接返回有类型的对象，集合返回 `{items,next_cursor}`；不额外包一层永远为 true 的 success。创建返回 201，普通读取／修改返回 200，异步触发一次共享刷新返回 202，删除草稿规则返回 204。

错误统一为：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "此活动刚刚有更新，请查看最新安排。",
    "field": null,
    "current_version": 9
  }
}
```

必要业务错误包括 `UNAUTHENTICATED`(401)、`FORBIDDEN`(403)、`NOT_FOUND`(404)、`VALIDATION_ERROR`(422)、`VERSION_CONFLICT`、`INVALID_TRANSITION`、`CANDIDATE_CHANGED`、`BILL_NOT_DRAFT`、`PAYMENT_PENDING`、`MEMBER_ALREADY_EXISTS`、`IDEMPOTENCY_CONFLICT`(409)。外部来源错误返回具体来源状态，不伪装成业务验证成功。

PATCH 只修改明确给出的字段。主键、归属、创建人和派生总额不能通过通用 PATCH 改写。所有 DTO 使用 Pydantic 定义并生成 OpenAPI，前端用 openapi-typescript 生成类型，CI 检查生成文件与后端一致。

### 10.2 身份与设置

| 方法与路径 | 输入 | 输出／行为 |
|---|---|---|
| `POST /auth/guest` | `display_name` | 创建访客 Cookie，返回 user |
| `POST /auth/register` | `username,password,display_name?` | 有访客会话则升级该身份，否则创建账户 |
| `POST /auth/login` | `username,password` | 建立会话 |
| `POST /auth/logout` | 无 | 销毁当前会话 |
| `GET /session` | 无 | `user,csrf_token`；未登录 user=null |
| `GET/PATCH /me` | `display_name,timezone,expected_version` | 当前用户资料 |
| `PUT /me/password` | `current_password,new_password` | 修改密码并撤销其他会话 |
| `GET/PUT /settings` | 全局费率、时区、游客配置、版本 | 管理员设置 |

### 10.3 时间与导入

| 方法与路径 | 输入 | 输出／行为 |
|---|---|---|
| `GET /me/availability` | `from,to,activity_id?` | 可编辑的本人规则 + 私人的解析区间 + revision |
| `POST /me/availability/rules` | `state,source,kind,span或recurrence,activity_id?,expected_revision` | 新规则与新 revision |
| `PATCH/DELETE /me/availability/rules/{id}` | 可编辑字段、revision | 仅本人规则；课程规则通过重导替换 |
| `POST /me/imports/wakeup/preview` | `share_text` | `preview_id,term,periods,busy_occurrences,summary` |
| `POST /me/imports/wakeup/confirm` | `preview_id,label,baseline_rules,expected_revision` | 事务替换导入并保存 baseline |
| `GET /me/imports` | 无 | 已导入来源元信息 |
| `DELETE /me/imports/{id}` | revision | 删除该导入及其 course 规则，不删手工规则 |

前端可以批量保存拖选产生的规则；为此 POST rules 同时接受 `rules: RuleCreate[]`，同一批次至多 100 条，所有规则共用一个 revision。单条输入也包装为长度 1 的数组，避免两种业务路径。

### 10.4 活动与成员

| 方法与路径 | 输入 | 输出／行为 |
|---|---|---|
| `GET /activities` | `scope=active/history/actionable,cursor` | 我参与的活动与待处理摘要 |
| `POST /activities` | ActivityCreate | 新活动和邀请 token |
| `GET/PATCH /activities/{id}` | ActivityPatch + expected_version | 详情快照／修改设置 |
| `POST /activities/{id}/clone` | 新标题与日期 | 新活动，不复制业务事实 |
| `GET /invites/{token}` | 无 | 公开邀请摘要 |
| `POST /invites/{token}/join` | 已有会话，或 `display_name` | 幂等加入，返回活动与用户 |
| `GET /activities/{id}/invite` | 无 | 主持人取得当前分享链接，不轮换 token |
| `POST /activities/{id}/invite` | `action=rotate/disable`、版本 | 主持人管理邀请 |
| `GET /activities/{id}/participants` | 无 | 成员、rsvp、到场状态 |
| `POST /activities/{id}/participants/offline` | `display_name` | 主持人补记临时球友 |
| `PATCH /activities/{id}/participants/{pid}` | `required?/membership?`、版本 | 主持人设置核心／移除成员 |
| `POST /activities/{id}/leave` | 无 | 本人退出；主持人需先转交 |
| `POST /activities/{id}/host` | `new_host_user_id,expected_version` | 转交主持人 |
| `PUT /activities/{id}/rsvp` | `plan_id,response=yes/no` | 当前拟参加者回应 |
| `PUT /activities/{id}/attendance` | `entries:[{participant_id,state}],verify` | 本人自报；host 可核对全员 |
| `POST /activities/{id}/participants/{pid}/claim-token` | 无 | 主持人生成临时球友认领链接 |
| `POST /participant-claims/{token}` | 当前登录身份 | 认领临时参与记录 |

### 10.5 候选、计划、场馆与订单

| 方法与路径 | 输入 | 输出／行为 |
|---|---|---|
| `GET /activities/{id}/availability` | `from,to` | 共享三态区间与共同时间，不包含课程原因 |
| `GET /activities/{id}/candidates` | `limit=20` | 候选、其他时间、来源新鲜度 |
| `POST /activities/{id}/plans` | `candidate_id,roster_participant_ids,expected_version` | 当前输入重新校验后选定 |
| `DELETE /activities/{id}/plan` | expected_version | 符合状态条件时回到 collecting |
| `POST /activities/{id}/reschedule` | `candidate_id,roster,old_booking_actions,expected_version` | 明确改约 |
| `GET/POST /activities/{id}/bookings` | BookingCreate | 订单列表／记录订场 |
| `POST /activities/{id}/bookings/{bid}/payment` | `amount_cents,payer_participant_id` | 记录一次真实垫款，关联一笔费用 |
| `POST /activities/{id}/bookings/{bid}/cancel` | `reason,expected_version` | 标记订单取消，不自动记退款 |
| `POST /activities/{id}/finish` | expected_version | 结束活动 |
| `POST /activities/{id}/cancel` | `reason,expected_version` | 取消活动 |
| `POST /activities/{id}/archive` | expected_version | 结清后归档 |
| `GET /venues` | 无 | 启用的场馆和来源配置摘要 |
| `GET /venues/{id}/slots` | `date` | 标准化快照与新鲜度 |
| `POST /venues/{id}/refresh` | `date,activity_id` | 成员触发共享查询，202 返回 refresh_key |
| `GET/POST/PATCH /settings/providers[/{id}]` | ProviderConfig | 管理员管理来源配置 |
| `POST/PATCH /settings/venues[/{id}]` | VenueConfig | 管理员管理场馆 |
| `PUT /settings/venues/{id}/manual-slots` | VenueDayResult、版本 | 人工来源编辑，走相同刷新事件 |

上表方括号是文档缩写，实际 OpenAPI 必须分别定义集合与具体资源路由。刷新完成通过 SSE 使 slots/candidates 失效，前端再 GET，不为每次刷新建一个永久任务表。

### 10.6 费用与账单

| 方法与路径 | 输入 | 输出／行为 |
|---|---|---|
| `GET/POST /activities/{id}/expenses` | ExpenseCreate | 费用列表／新增实际支出 |
| `PATCH/DELETE /activities/{id}/expenses/{eid}` | ExpensePatch + version | draft 内编辑／作废 |
| `POST /activities/{id}/expenses/{eid}/refunds` | `amount_cents<0,payer_participant_id,allocations?` | 关联原费用记录实际退款 |
| `GET /activities/{id}/bill/preview` | 无 | 费用分配、余额、转账计划、bill_generation |
| `POST /activities/{id}/bill/publish` | `expected_generation` | 新账单快照与 issued/settled 状态 |
| `GET /activities/{id}/bill` | `revision?` | 当前或历史只读账单与付款进度 |
| `POST /activities/{id}/bill/reopen` | `reason,expected_generation` | 回到 draft，保留 confirmed 转账 |
| `POST /activities/{id}/payments` | `bill_revision_id,transfer_id,amount_cents` | 本人付款声明 |
| `POST /activities/{id}/payments/{pid}/confirm` | 无 | 指定收款人确认 |
| `POST /activities/{id}/payments/{pid}/reject` | `reason?` | 指定收款人退回 |
| `POST /activities/{id}/payments/{pid}/withdraw` | 无 | 付款人撤回未确认声明 |

创建正向费用的 POST 不接受 kind=refund；负费用只通过关联原支出的 refunds 接口创建。

### 10.7 写入示例

ActivityCreate 的可选 price_overrides 只表示用户显式覆盖；服务端读取全局与场馆设置生成完整 price_defaults 快照。PATCH 活动沿用 price_overrides，不能直接覆盖只读快照来源字段。

创建活动：

```json
{
  "title": "周末打球",
  "timezone": "Asia/Shanghai",
  "date_from": "2026-09-19",
  "date_to": "2026-09-20",
  "daily_windows": [{"weekdays": [6, 7], "start_time": "14:00", "end_time": "22:00"}],
  "duration_minutes": 120,
  "min_players": 4,
  "max_players": 6,
  "court_count": 1,
  "venue_preferences": ["venue-a"],
  "decision_deadline": "2026-09-18T22:00:00+08:00",
  "price_overrides": {"court_hourly_cents": 6000, "shuttle_unit_cents": 1200}
}
```

指定人员均分支出：

```json
{
  "kind": "extra",
  "description": "停车",
  "amount_cents": 2000,
  "payer_participant_id": "pc",
  "split_mode": "equal",
  "split_scope": "selected",
  "shares": [{"participant_id": "pa"}, {"participant_id": "pc"}]
}
```

精确分摊沿用该结构，将 split_mode 设为 exact，每个 share 提供 `exact_amount_cents`。动态全体到场者使用 `split_scope=attendees,shares=[]`；发布前由后端展开，前端不自行计算应付净额。

## 11. 实时事件与通知投递

### 11.1 事件契约

```json
{
  "id": 183,
  "type": "expense.created",
  "activity_id": "activity-a",
  "actor_user_id": "user-b",
  "resource_version": 12,
  "occurred_at": "2026-09-19T20:10:00+08:00",
  "payload": {"expense_id": "expense-b", "bill_generation": 5}
}
```

使用的事件类型固定列出：`activity.created/updated/cancelled/finished/archived`、`participant.joined/left/updated`、`availability.changed`、`venue.changed/stale`、`plan.selected`、`booking.recorded/confirmed/cancelled`、`rsvp.changed`、`attendance.changed`、`expense.created/updated/voided`、`bill.published/reopened/settled`、`payment.claimed/confirmed/rejected/withdrawn`。

SSE 事件只包含需要重新获取的资源标识、版本和少量非敏感摘要；完整数据经过各查询接口自己的权限投影返回。个人日程变更发布一个本人事件，并针对有关活动产生重新计算信号，不向无关活动广播。

### 11.2 SSE 连接

`GET /api/v1/events?watch_activity_id=<当前活动>` 使用当前 Cookie 验证身份。watch 参数可省略；每个页面只开一条 EventSource。服务端只投递当前用户有权限的活动事件和本人通知事件，不能仅凭 watch_activity_id 订阅别人活动。移除成员或撤销会话后，已有连接也重新检查可见范围。

响应头：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`。每 15 秒发送注释心跳。后台事件派发器每秒批量读取新增 events，扇出到当前进程连接队列；不要让每条浏览器连接各自轮询数据库。

```text
id: 183
event: resource.changed
data: {"activity_id":"activity-a","resource":"bill","version":12}

```

首次连接返回 `ready` 和当前 cursor，前端随后取得页面快照；快照请求期间收到变更则标记 dirty，返回后再刷新一次。刷新请求携带本地顺序号，旧请求晚返回时不得覆盖新状态。成员操作成功可以先显示服务器返回的新对象，SSE 再进行统一失效更新。

连接中断后由 EventSource 重连并携带 Last-Event-ID。服务端回放该用户仍有权限的事件；事件保留 7 天，cursor 早于保留范围时发送 `reset`，前端重新取得快照。响应中不携带过时完整页面来覆盖新数据。[T2]

页面隐藏时关闭事件连接，可见时重新打开并刷新快照；连接存在时 watch_activity_id 被计作活跃观看者。正常一次变更到另一浏览器展示的目标延迟不超过 2 秒，外部场地发现延迟另受查询周期约束。

### 11.3 派生通知

一个后台 worker 读取未 processed 的 events，计算是否需要通知，在短事务中写 notifications 并标记 event processed。所有通知有业务 dedupe_key，重复消费事件不会产生两条同一通知。定时提醒使用 `activity:{id}:plan:{plan_no}:reminder:2h` 这类确定 key。

公开群通知写入对应 bot_context；个账消息写一条 Web 用户通知，若已绑定可主动私聊的 UMO，再写一条具体私聊 context 通知。用户通知在网页中直接可读，不等待 Bot。推荐和加入进度通过 available_at 延后合并，重要的订场确认／取消／账单事件立即可投递。

UI 使用 `GET /notifications?unread=true` 与 `POST /notifications/{id}/read`。活动简要记录使用 `GET /activities/{id}/events?before=<seq>`，同样过滤课程、凭据和其他私人内容。

## 12. AstrBot 插件与 Bot API

### 12.1 集成方向

插件向 Web 服务发起 HTTP 请求，不要求 Web 服务连接 AstrBot 管理后台。主动推送采用**服务器持久化通知、插件长轮询取出并发送**的方式：无需给 Bot 额外开放入站端口，也无需依赖某个版本管理面板的 HTTP API。

插件用官方 `@filter.command_group("羽球")` 注册指令，读取事件中的真实 sender_id、platform_id、message_id 和 unified_msg_origin。主动消息通过 `context.send_message(umo, MessageChain)` 发送，这是官方文档给出的机制。[T5][T6]

插件配置只需 `base_url`、`bot_key`、`api_token`。base_url 为 ShuttleUp 的 HTTPS 地址。服务端通过环境变量配置可接受的 bot_key 与服务 token；前端不接触 token。插件卸载或重载时关闭 httpx client 和轮询协程。

### 12.2 命令请求

```http
POST /bot/v1/commands
Authorization: Bearer <service-token>
Idempotency-Key: astrbot:qq:message-123
Content-Type: application/json
```

```json
{
  "bot_key": "main",
  "platform_id": "qq",
  "sender_id": "12345678",
  "umo": "平台实际返回的完整UMO，不自行拼装",
  "message_id": "message-123",
  "command": "expense.create",
  "activity_code": "B6R2",
  "args": {"kind": "shuttle", "quantity": 4}
}
```

服务端从认证 token 决定 bot_key，并要求请求声明一致；通过 bot_identity 解析用户。客户端不能传入任意 Web user_id 代表他人。只接受已实现的 command 枚举与对应 Pydantic 参数模型，不提供执行任意服务方法的反射入口。

返回统一回复结构：

```json
{
  "command_id": "cmd-123",
  "reply": {
    "mode": "same_context",
    "text": "已记录球费 ¥48.00：4 个 × ¥12.00，垫付人：你。费用编号 E3K7。",
    "links": [{"label": "查看费用", "path": "/a/activity-a/bill"}]
  },
  "resource": {"type": "expense", "id": "expense-1", "version": 1}
}
```

`mode` 为 `same_context/private`。服务端返回相对 path，插件使用配置的 base_url 拼接；不接受聊天用户提供任意 URL 作为登录或收款入口。账单在群里请求时，同群回复“已私发个人账单”或仅公开账单入口，具体个人余额使用绑定的私聊 UMO 发送。

### 12.3 命令到服务映射

| Web/Bot 业务名称 | Bot command 枚举 | 调用或返回 |
|---|---|---|
| 帮助 | `help` | 固定帮助模板 |
| 绑定账户／关联群 | `identity.bind` / `context.bind` | 消耗对应一次性 token |
| 创建／列出／当前／切换 | `activity.create/list/current/switch` | 活动服务与 context 当前指向 |
| 加入／退出 | `participant.join/leave` | 相同成员服务；join 通过已授权群关联判断范围 |
| 课表 | `schedule.open` | 个人时间页 |
| 有空／没空 | `availability.set` | 规则服务，state=free/busy |
| 时间／推荐／场地 | `availability.summary` / `candidate.list` / `venue.list` | 相同查询服务 |
| 选择／已订 | `plan.open_select` / `booking.open_create` | 带稳定候选 ID 的网页表单 |
| 参加／不参加 | `rsvp.set` | 相同 rsvp 服务 |
| 到场／缺席 | `attendance.set` | 本人到场状态 |
| 场地／球／AA 记账 | `expense.create` | 本人垫付；quantity 或整数 amount_cents |
| 指定人员记账 | `expense.open_split` | 预填金额的费用抽屉链接 |
| 账单 | `bill.show` | 本人视角 DTO |
| 已付／收款 | `payment.claim/confirm` | 指定转账或付款声明对应服务 |
| 结算／结束／取消 | `bill.open_publish/activity.open_finish/activity.open_cancel` | 对应确认页，不先执行状态切换 |

所有指令的中文语法以 PRD 表格为准。解析器只解析明确的日期、时段、金额和命名参数；无法匹配时回复该指令的一个有效示例，不调用 LLM 猜测。Bot 记账球的“4个”和球费的“48”走不同参数模型。指定活动短号优先于 context.current_activity_id；未指定且没有当前活动时只返回本群活动选择列表。

重复的平台 message_id 返回相同 command 结果，不再次写账。只生成操作链接的请求也不提前创建空费用或空订单。

### 12.4 绑定 API

Web 提供 `POST /me/bot-bind-token`、`POST /activities/{id}/bot-bind-token`、`DELETE /me/bot-identities/{id}` 与 `DELETE /activities/{id}/bot-links/{link_id}`。token 使用 12 位随机字母数字，10 分钟有效，单次消费。Web 账号绑定要求在私聊执行，绑定后保存 private_umo；群绑定只允许 Web 主持人的已绑定平台身份消费。

UMO 作为平台给出的不透明字符串保存，不能由 QQ 群号或 Telegram ID 自行猜测拼装。[T6] 一个 context 可以关联多场活动；切换当前只修改 current_activity_id，不关闭其他活动通知。

### 12.5 通知长轮询 API

| 方法与路径 | 行为 |
|---|---|
| `GET /bot/v1/deliveries?wait=25&limit=20` | 等待该 bot_key 可发送通知，原子租用并返回 |
| `POST /bot/v1/deliveries/{id}/ack` | 发送成功，记录平台 message_id（若可取得） |
| `POST /bot/v1/deliveries/{id}/fail` | 记录本次错误、释放租约并设置下一次尝试时间 |

返回示例：

```json
{
  "items": [{
    "id": "notification-1",
    "lease_token": "一次租用随机值",
    "umo": "已绑定的目标UMO",
    "event_type": "booking.confirmed",
    "text": "周六 18:00–20:00，A馆 3号场，已订好。",
    "links": [{"label": "查看活动", "path": "/a/activity-a"}]
  }]
}
```

通知租约 60 秒，ack/fail 必须带相同 lease_token；保存租约 token 的哈希。插件限制并发投递，调用官方发送接口完成后再 ack。失败后按 5/30/120/600 秒间隔重试，累计 5 次失败在设置页显示为 failed，管理员可重试。这是有限的消息投递机制，不用于反复重试已经失败的业务操作。

业务命令可以严格幂等；IM 平台若不支持发送幂等，在“已发出但 ack 未到达”的瞬间仍可能重复展示消息，因此插件回复附活动短号和账单版本，后台不以 IM 送达来决定是否扣款或是否订场成功。

## 13. 前端实现与视觉规格

### 13.1 设计令牌

```css
:root {
  --bg: #f7f8f5;
  --surface: #ffffff;
  --text: #182923;
  --muted: #5d6d64;
  --line: #e1e7e2;
  --primary: #087f72;
  --primary-soft: #e5f4ef;
  --danger: #b33b3b;
  --warning: #875d12;
  --unknown: #edf0ee;
  --radius-card: 16px;
  --radius-control: 10px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --content-width: 1200px;
  --control-height: 44px;
}
```

基础字体采用 `-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif`，数字使用 `font-variant-numeric: tabular-nums`。正文 15–16px、行高 1.5；页面标题 26px/34px；候选时间 22px/30px；主要账款 32px/40px；辅助说明 13px/20px。

只有主操作使用实心青绿按钮，其余为白底描边或文字按钮。边框承担主要分组作用，阴影仅用于悬浮层和极轻的卡片浮起。金额右对齐，时间区间使用一致的短横线格式。按钮和状态不依赖 emoji 表达。

### 13.2 活动页布局

```text
桌面（最大 1200px）
┌───────────────────────────────────────────────────────────────┐
│ ShuttleUp                         我的时间      个人头像       │
│ 周末打球                         收集时间        分享邀请      │
│ 安排    成员    费用                                         │
├───────────────────────────────────────┬───────────────────────┤
│ 推荐方案                              │ 这场球的进度          │
│ 周六 18:00–20:00                      │ 5/6 已提交时间        │
│ A馆 · 2 块连续可用 · ¥120             │ 拟参加成员头像        │
│ 5 人有空              [选择这个方案] │                       │
│                                       │ 我的时间              │
│ 其他两个候选                          │ [修改本次时间]        │
│                                       │                       │
│ 共同时间表（可折叠）                  │ 最新活动记录          │
└───────────────────────────────────────┴───────────────────────┘
```

手机页面顶部保留标题、状态和分享，标签固定在内容上方。主要候选单列，成员进度移到候选上方的一行摘要；“共同时间”默认折叠。底部操作栏依据角色与状态显示一个主动作：加入、填写时间、选择方案、登记订场、回应参加或结算。

已确定活动将候选区替换为固定集合卡：具体日期、时间、场馆地址、球场、回应名单。账务阶段主卡优先显示个人应付／应收。收集、确认、结算三个阶段仍是同一活动页的不同内容，不重新发明三个页面体系。

### 13.3 时间编辑器

桌面七列日期 + 时间轴，15 分钟一格，支持鼠标 pointer drag；手机默认单日／三日，点击起止点后显示小型操作条。控件另提供日期和起止时间表单，键盘与触屏均可使用。

时间格的颜色来自最终解析状态；个人编辑模式用边界和小标签区分“本次覆盖”和“基础规则”。只画活动允许的时间范围，展示周切换。拖选区间提交后用后端解析结果替换，不由前端自行复刻优先级算法。

### 13.4 组件边界

基础组件：Button、TextField、Select、Dialog/Drawer、Toast、Badge、Tabs。领域组件：CandidateCard、AvailabilityGrid、ParticipantList、BookingSummary、ExpenseEditor、BillSummary、TransferRow、FreshnessLabel。

可访问的 Dialog/Drawer 可以使用一个按需导入的轻量 headless 依赖，或正确实现 focus trap、Escape、焦点恢复；不引入整套组件库只为了一个弹窗。日期和时间输入尽量用原生控件，补足统一标签与样式。

应用状态仅分 session、当前活动查询缓存、编辑表单草稿。使用 composable 和 typed fetch 即可，不同时引入多个全局状态库。金额计算、时间覆盖和候选排名都以后端结果为准。

### 13.5 实时更新与视觉稳定

SSE 到达后按 resource 使对应查询失效，150ms 内合并重复刷新。不关闭用户正在填写的抽屉、不重置表单、不滚回顶部。候选排序有变化时保留当前滚动和正在操作的卡片，显示“方案已更新”小提示，在用户结束操作后应用新排序。

只读页面允许自然刷新；编辑表单遇到版本变化保存原输入并指示需要核对的字段。输入和提交按钮有明确 loading 状态，但普通点击不添加多重确认弹窗。过期场地显示“待刷新 · 最近成功 12:00”，不把整页替换成错误大图。

### 13.6 分享与可用性

分享卡先交付可复制文本与邀请链接，不依赖图片生成服务。移动端可用时调用原生 Web Share，否则使用复制按钮；这是同一分享功能的浏览器能力差异，不做额外分享平台集成。

测试至少覆盖 390×844、768×1024、1280×800。截图检查主按钮层级、金额对齐、空状态和弹窗键盘操作。页面级横向滚动为失败；局部时间表可以在明确容器内切换日期。核心文本对比度达到 4.5:1，触控目标不小于 44px。

## 14. 测试与验收数据

### 14.1 纯算法测试

时间测试覆盖层级覆盖、同层最后编辑、生效期、左右开闭、跨天、课程指定周次、缺省 unknown、活动隔离，以及同区间包含一段 busy 时整段不是 free。候选测试覆盖人数上限、核心成员、多个场数、固定球场连续性、分段报价和未知价格。

金额测试覆盖 100 元三人分摊、2 分四人分摊、1 分三人分摊、多付款人、精确分摊、多次退款、部分转账、修订保留付款。必须检验 `0.02 元 / 4 人 = [0.01,0.01,0,0]`，任何正支出不能出现负分摊。

性质测试使用固定随机种子生成不少于 1000 组数据：均分守恒、精确分摊守恒、全体净额之和为零、按生成转账全部确认后净额归零、打乱输入顺序不改变按 join_order 的确定结果。

### 14.2 API 与权限测试

用临时 SQLite 文件而不只用内存库，验证 WAL、事务、迁移和重启。至少三套会话：主持人、成员、未加入者。以真实 HTTP 请求测试状态转换、越权、CSRF、邀请撤销、重复提交费用、并发确认同一付款以及过期 candidate。

测试 `record_booking` 只在完整覆盖时确认活动；未支付订单不记垫付；一次实际付款同时生成费用和事件。出账过程与另一个费用写入竞争时，只允许基于正确 generation 的版本发布。

### 14.3 浏览器端到端场景

E2E 使用四个独立 browser context，跑完 PRD A01–A31 可自动化的业务路径。重点场景不使用前端拦截假 API：数据库和后端真实启动，只有外部场馆 HTTP、WakeUp HTTP 和 IM 发送替换为固定 fixture。

至少完成两个全流程：正常四人打球并分次结清；活动取消后处理不可退费用和实际退款。实时测试在两个已打开页面修改时间，验证另一页面在 2 秒目标内更新。Bot 模拟发送同一 message_id 两次，数据库只新增一笔费用。

### 14.4 固定验收数据

测试 clock 注入固定 `2026-09-18T12:00:00+08:00`，不依赖执行当天日期。开发演示种子使用相对未来日期，避免演示打开即过期。所有样本标记 `demo/test` 来源。

A/B/C/D 为四位测试成员，join_order=1/2/3/4；场地费用 A 垫 12000 分，球费 B 垫 4800 分，停车 C 垫 2000 分由 A/C 均分。期望净额 `[6800,600,-3200,-4200]`，期望转账 `D→A 4200、C→A 2600、C→B 600`。

第二份样本含 5 位成员、一个 unknown、一位核心成员、一条活动局部忙碌覆盖、一组不连续的场地以及一组仅聚合余量，用于展示候选差异。真实 Provider 联调另保存去除凭据的响应，不把演示数据标成生产网站。

## 15. 运行、部署与性能预算

### 15.1 开发命令契约

以下命令是仓库需要实现并在 README 验证的入口，不代表当前骨架已经包含全部脚本：

```bash
uv sync --group dev
uv run alembic -c backend/alembic.ini upgrade head
uv run shuttleup admin create
uv run uvicorn shuttleup.app:app --reload --port 8000

npm --prefix frontend ci
npm --prefix frontend run dev

uv run pytest backend/tests
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

包配置须让根目录 `uv run` 正确发现 backend/shuttleup。Vite 开发服务器将 `/api` 和 SSE 转发到 Python；生产静态资源复制到 Python 包的 static 目录。构建时生成静态文件，生产不运行 npm。

### 15.2 环境配置

```dotenv
APP_BASE_URL=https://shuttleup.example
APP_TIMEZONE=Asia/Shanghai
APP_SECRET=replace-with-a-random-secret
DATABASE_URL=sqlite:////data/shuttleup.db
SESSION_COOKIE_SECURE=true
ASTRBOT_MAIN_TOKEN=replace-with-a-random-service-token
LOG_LEVEL=INFO
```

`.env.example` 仅包含说明和占位值；实际凭据不提交。场馆 Provider 的 credential_env 指向部署环境中的专用变量名。生产环境将 `/data` 挂载为持久卷。

多阶段 Dockerfile 在 Node 构建阶段编译前端，在 Python 运行阶段安装锁定依赖并复制前端。默认镜像不包含 Chromium。`compose.yaml` 只有 app 服务和数据卷；对公网部署可接用户已有 HTTPS 反向代理，文档提供一份简短配置，并禁用 SSE 缓冲。

容器启动先执行数据库迁移再启动单 worker 服务。`GET /healthz` 检查进程，`GET /readyz` 检查数据库与迁移状态。来源故障在设置页单独呈现，不让某个场馆不可用变成整个应用不就绪。

备份命令 `shuttleup backup /path/to/backup.db` 使用 SQLite backup API；恢复使用停止服务后替换数据库的操作说明。日志记录请求 ID、状态、耗时、来源查询摘要和通知结果，不记录课程口令、Cookie、密码或 Bot token。

### 15.3 预算与测量

| 指标 | 验收目标与测量条件 |
|---|---|
| 部署规模 | 一个 app 服务、一个持久数据卷 |
| 内存 | 不含浏览器型 Provider：空闲 RSS 目标 <180MB，512MB 容器限制下通过完整 E2E |
| 首屏资源 | 活动页初始 JS ≤180KB gzip，CSS ≤30KB gzip |
| 数据规模 | 100 用户、20 场待处理活动、每场最多 30 人、14 天查询范围 |
| 普通 API | 1 vCPU 条件下，20 并发用户常用内部查询 p95 <300ms；不含外部网络等待 |
| 候选计算 | 30 人、3 场馆、14 天样本的单次纯计算目标 <100ms |
| 人员／账单同步 | 服务端提交到另一已打开页面目标 ≤2 秒 |
| 场地同步 | 网站查询周期 + 查询耗时 + 页面同步，界面始终展示实际查询时间 |

这些是测试预算，需要写入实测报告；达不到时先定位慢查询、重复计算或依赖体积，不直接新增缓存服务。若之后确有持续写入瓶颈，迁移数据库到 PostgreSQL；跨进程派发器和独立 worker 在那时再替换现有接口，V1 不提前部署。

## 16. Codex 分阶段实施计划

按可使用的纵向切片开发，每阶段同时交付对应界面、API、测试和简短运行说明。不要先把全部数据库表和空路由铺完，再把前端留到最后。

| 阶段 | 实现内容 | 阶段完成条件 |
|---|---|---|
| M0 基础体验 | 项目结构、锁文件、迁移、登录／访客、视觉令牌、主页壳、CI | 可启动并创建账户；手机与桌面基础布局完成 |
| M1 约人约时间 | 创建活动、邀请加入、手工周期／一次性规则、共同时间、SSE | 两个浏览器加入同活动，修改忙闲自动同步；A01–A03、A06–A09 |
| M2 WakeUp | 分享预览、规范化、确认替换、课程周次、个人时间编辑器 | 课程 fixture 全通过，真实口令联调通过；A04–A07 |
| M3 场地与方案 | Provider 协议、人工与 JSON 源、首个真实站点、轮询、连续场地算法、候选卡 | 不连续场地不能组成推荐；真实查询可见；A10–A16 |
| M4 确定一场球 | 名单、RSVP、多个订单、支付登记、改约、到场、结束／取消 | 一场活动由 collecting 到 finished，可取消并保留费用；A15–A18、A21 |
| M5 完整分账 | 全局费率、球费、指定分摊、出账、部分付款、确认、修订、退款、归档 | 金额性质测试及两个结算流程通过；A19–A26 |
| M6 AstrBot | 身份绑定、群关联、全部指令、通知长轮询、群消息模板 | 测试插件 + 实际 Bot 完成创建、记账与主动通知；A27–A29 |
| M7 完整验收 | 响应式完善、E2E、部署、备份恢复、性能预算、来源联调记录 | A01–A32 全部有结果，演示来源与真实来源明确分离 |

每阶段建立一个清晰提交，更新 `docs/IMPLEMENTATION-STATUS.md`：已实现需求编号、运行命令、通过的测试、真实接入状态。只按实际执行结果打勾；完成 M0/M1 不等于应用交付完成。

真实 WakeUp 口令或目标网站尚未提供时，可以继续开发其他模块和基于已取得样本的契约测试；对应“真实联调”条目保持未验收。不能用人工录入替代已承诺的 WakeUp 分享导入，也不能用固定假场地替代网站爬取功能。

## 17. 核心一致性检查表

完成实现前逐项检查以下不变量。它们是产品正确性的定义，不是增加用户操作的额外流程。

| 范围 | 必须成立 |
|---|---|
| 身份 | 一个活动的一个 Web 用户只有一条 participant；主持人身份由后端关系决定 |
| 时间 | 空白是 unknown；只在完整时长全部 free 时计为有空；本次规则不泄露到其他活动 |
| 场地 | 具名同场连续；聚合数量不冒充具体场地；过期余量不参与 verified |
| 活动 | 选方案不等于订场；预约网站余量变动不撤销本地已登记的订单 |
| 人员 | 可用时间、拟参加、回应、实际到场不混同 |
| 费用 | 估计不等于垫付；正支出分配不出现负值；每笔分摊总和等于该笔金额 |
| 付款 | 声明不等于到账；收款人确认后才计入余额；重复请求不重复入账 |
| 修订 | 历史快照不变；已确认转账保留；新账单只计算实际剩余债务 |
| 取消 | 活动取消不删除费用、退款或已确认转账 |
| 同步 | Web 与 Bot 调用同一业务服务；事件与业务事务一起提交 |
| 界面 | 核心操作在手机可完成；主要按钮只有一个；输入中的表单不被实时更新冲掉 |

## 18. 外部依据与联调记录

资料核对日期：2026-09-11。下面的资料支撑外部机制；表结构和业务算法属于本项目的实现设计。

- [T1] FastAPI 官方 Lifespan Events：`https://fastapi.tiangolo.com/advanced/events/`
- [T2] MDN Using server-sent events：`https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events`
- [T3] SQLite 官方 Write-Ahead Logging，含并发说明与 WAL-reset 修复说明：`https://www.sqlite.org/wal.html`
- [T4] WakeUp 官方导入说明与分享数据生命周期：`https://www.wakeup.fun/doc/import_schedule.html`、`https://www.wakeup.fun/policy.html`
- [T5] AstrBot 官方消息事件与指令组：`https://docs.astrbot.app/dev/star/guides/listen-message-event.html`
- [T6] AstrBot 官方主动消息与 UMO：`https://docs.astrbot.app/dev/star/guides/send-message.html`
- [T7] Vue 官方性能建议，含构建、按需依赖与包体控制：`https://vuejs.org/guide/best-practices/performance`

真实联调材料保存到 `docs/integrations/`：WakeUp 的已验证分享请求与字段映射、首个场馆的查询范围与刷新频率、已脱敏响应位置、AstrBot 的实际安装版本及一次指令／主动消息测试结果。不用口述“已兼容”代替这些记录。
