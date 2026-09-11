# WakeUp 分享导入联调

- 契约：`backend/shuttleup/availability/wakeup.py` 将上游响应标准化，再展开为带偏移的明确课程区间。
- 已验证：脱敏 fixture 覆盖奇数周、偶数周、不连续周次、不同节次间隔和明确日期调课；原口令及课程名称不入库。
- 真实联调：**待项目使用方提供一份联调时有效的 WakeUp 分享口令**。
- 部署配置：真实请求地址通过 `WAKEUP_SHARE_ENDPOINT` 由运维注入；在现场确认当前请求/响应后，记录字段映射并加入脱敏 fixture。未经现场验证的 URL 不会写死为官方接口。

