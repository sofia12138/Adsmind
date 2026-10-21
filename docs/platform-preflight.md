# 平台执行预检与 dry-run 契约

平台预检只消费状态为 `READY` 的应用广告草稿所冻结的
`ad_creation_execution_snapshot.v1`。预检不会回读账户组、命名规则、创意组、
素材版本等可变业务对象，也不会调用 Meta、TikTok、YouTube 或其他外部平台。

## 数据边界

- `app_platform_account_mappings`：当前租户与应用持有的快照账户到平台账户、凭证标识的映射。
- `app_platform_material_mappings`：当前租户、应用、平台账户下，冻结素材版本到平台素材编号的映射及上传状态。
- `app_platform_preflight_runs`：快照哈希、结构化阻断原因、dry-run 计划、计划哈希和幂等执行键。
- `app_platform_preflight_audit`：预检完成及真实执行拒绝事件的追加式审计记录。

所有查询都绑定已验证的 `tenant_id + application_id`。预检使用客户端提供的 UUID
`request_key` 做幂等：相同键与相同草稿/快照返回原记录；相同键用于其他草稿或快照会返回冲突。

## 预检项目

1. 草稿必须为 `READY`，快照契约、草稿编号、租户/应用范围及 SHA-256 必须一致。
2. 快照必须明确 `external_write_authorized=false`，且账户、名称预览、创意素材结构完整。
3. 每个冻结账户必须存在当前应用的 ACTIVE 账户映射；映射引用的凭证必须存在且未过期。
4. 冻结素材状态必须为 `uploaded`，且每个账户必须有对应素材版本的 uploaded 平台映射。
5. Campaign、Ad group、Creative 冻结名称不能为空、不得超过 255 字符或包含控制字符。

失败项写入 `blocking_reasons`，每项包含稳定 `code`、可读 `message` 和相关上下文。

## 永久 dry-run 边界

计划契约固定为 `ad_platform_dry_run_plan.v1`，并强制：

- `dry_run=true`
- `executable=false`
- `external_write_authorized=false`

数据库包含对应 CHECK 约束，服务没有真实平台客户端依赖。`POST
/api/platform-preflight/runs/{run_id}/execute` 始终拒绝并记录 `execution.denied`
审计事件，不能把 dry-run 记录提升为真实执行。

未来若增加真实执行，必须使用独立的审批和执行契约、独立权限与入口，不得修改或复用
dry-run 记录作为授权。执行前还必须重新核验审批绑定的快照哈希、账户/素材映射版本、凭证状态，
并以平台 + 账户 + 快照哈希 + 操作步骤组成稳定幂等键；超时或结果未知时必须停止重试并人工对账。
