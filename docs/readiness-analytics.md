# AdsMind 只读投放准备就绪度分析

## 范围与边界

`GET /api/readiness-analytics/overview` 和 `GET /api/readiness-analytics/details`
只读取已验证的 `tenant_id + application_id` 作用域内现有记录。接口不会写数据库、
上传素材、调用广告平台、创建广告、修改预算或把 dry-run 计划转成真实执行。

这份数据用于回答“当前应用距离可进入后续人工流程还有哪些准备项”，不是广告效果、
消耗、ROI 或平台实际投放报表。没有记录、未知、缺失和未运行都不能解释为 0 或成功。

## `readiness_analytics.v1` 口径

- 素材：只统计当前应用在 `app_application_materials` 中选择的素材。`latest` 使用主档最新
  版本，`pinned` 使用固定版本。缺少有效版本计为 `missing`；无法识别的上传状态计为
  `unknown`，不会并入 `uploaded`。
- 创意组：复用创意组领域模块的实时 `can_deliver` 和 `blocking_reasons`。可投放率分母只含
  明确的 `deliverable + blocked`，`unknown` 不进入分母。
- 广告草稿：`READY` 单列；`DRAFT` 且已有阻断原因计为 `blocked`；没有阻断但尚未标记
  READY 计为 `pending`；其他状态计为 `unknown`。
- 平台预检：每条不可变 dry-run 记录按 `PASSED`、`BLOCKED` 或 `unknown` 统计。READY 草稿
  没有任何预检记录时生成只读的 `not_run` 明细项，不回写源表。
- 预检阻断原因：按 BLOCKED 预检记录中每个结构化 `blocking_reasons[].code` 计数。同一记录
  内不同账户产生的相同 code 会分别计数，因此它代表原因出现次数，不是受影响草稿数。
- 最近变化：取当前返回来源记录中的最大时间。没有时间返回 `null`，前端展示“暂无变化记录”。

## 明细与追溯

明细支持 `entity_type`、`status`、`reason_code`、`query`、`page` 和 `page_size` 筛选。
每项包含来源对象 ID、状态、结构化原因、最近变化时间、元数据及站内追溯链接。
`query` 只搜索当前作用域内已加载的名称、ID 和元数据，不跨租户或应用。

## 权限

接口要求当前用户已登录、属于请求租户、能访问请求应用，且应用角色为
`owner/admin/editor/viewer`。前端入口复用现有 `platform_preflight` 面板权限，避免本 Session
新增面板定义或数据库迁移；后续若需要独立授权，可在单独迁移中新增专用 panel key。
