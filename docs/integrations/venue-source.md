# 场馆来源扩展

主项目提供人工数据、标准 JSON 协议、通用快照缓存和场馆登录维护界面。特定网站的地址、参数、协议实现、样本和凭据不纳入版本控制。

## 本机扩展

将可选扩展放入 `.local/<extension>/`；整个 `.local/` 已被 Git 忽略。每个扩展的 `__init__.py` 提供 `providers` 工厂映射，可按需提供 `register_cli`、`credential_revision`、`login_status`、`start_login` 和 `cancel_login`。只加载本机文件，不从网络下载代码。

无本机扩展时项目仍能启动；已有数据库引用未安装的来源会显示 `ADAPTER_UNAVAILABLE`。本机扩展应在自己的目录中保存依赖清单、说明和测试。数据库、凭据、运行状态留在已忽略的 `data/`，不要向来源的公开配置写入令牌。

## 登录维护

管理员在「可用场地」页面查看最近验证时间，点击「更新场馆登录」。支持桌面更新的扩展会打开服务器本机终端，用户在终端完成系统验证，再在原网站登录入口打开页面。网页不接收系统密码或令牌。

采集期间显示进度，可取消；超时、取消或验证失败不应替换原凭据。新凭据须通过独立查询和数据解析后才能启用，随后恢复来源查询。扩展负责清理临时证书和采集进程。

`AUTH_REQUIRED`、`AUTH_EXPIRED`、`AUTH_REJECTED`、`CREDENTIAL_PERMISSIONS` 会暂停整个来源的自动查询，不再对其他日期重试。凭据版本变化时允许重新验证；成功后解除暂停。身份状态随数据库保存，重启不会丢失。暂停来源的旧数据不能用于有效候选。

管理员接口：

- `GET /api/v1/settings/providers/{id}/login`：维护状态。
- `POST /api/v1/settings/providers/{id}/login`：启动或复用当前更新任务。
- `DELETE /api/v1/settings/providers/{id}/login`：取消更新。

写操作要求管理员会话和 CSRF。API 不返回凭据；只能启动本机扩展预先定义的操作，不能提交命令或文件路径。

## 通用查询

`GET /api/v1/venues/{id}/slots?date=YYYY-MM-DD` 按需复用或获取快照；`POST /api/v1/venues/{id}/refresh?date=YYYY-MM-DD` 请求共享刷新，不绕过来源冷却。日期范围为今天至 31 天后，不代表来源实际开放天数。

快照消费者须检查 `fresh` 和 `last_error_code`；过期数据仅用于历史查看。`available_count` 表示有效的「球场×时段」格数。进程内并发锁适用于单 worker；多进程部署需要分布式租约。
