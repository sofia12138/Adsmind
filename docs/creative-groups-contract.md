# 应用级创意组接口契约（0007）

## 范围与边界

- 创意组属于 `tenant_id + application_id`，所有 HTTP 请求必须经过 JWT、租户成员和
  `X-Application-Id` 应用归属校验。
- 创意组只能引用当前应用已存在于 `app_application_materials` 的素材。
- 每条引用只保存 `material_id + selection_mode + selected_version_id`，不保存或伪造平台素材 ID。
- 本阶段只管理草稿，不创建广告、不建立平台素材映射、不推送素材、不执行预审核。

## HTTP 接口

| 方法 | 路径 | 应用角色 | 用途 |
| --- | --- | --- | --- |
| GET | `/api/creative-groups` | owner/admin/editor/viewer | 当前应用列表 |
| GET | `/api/creative-groups/{id}` | owner/admin/editor/viewer | 当前应用详情 |
| POST | `/api/creative-groups` | owner/admin/editor | 新建草稿 |
| PUT | `/api/creative-groups/{id}` | owner/admin/editor | 整体更新草稿 |
| DELETE | `/api/creative-groups/{id}` | owner/admin/editor | 删除草稿 |

跨租户、同租户另一应用以及引用了其他应用素材的请求统一表现为 404，不暴露资源是否存在。
所有新建、更新、删除操作写入 `creative_group` 类型审计日志。

## 版本语义

- `latest`：必须令 `selected_version_id=null`。读取创意组时动态解析素材主档的当前最新版本；
  新版本登记后，创意组会自动跟随并重新计算可投放状态。
- `pinned`：必须提供 `selected_version_id`。该版本必须属于同租户、同一素材；后续登记新版本
  不会改变创意组解析出的版本。
- `effective_version_id` 和 `selected_version_number` 是当前解析结果；广告创建阶段不得自行重新
  猜测版本。

## 广告创建阶段消费契约

广告创建阶段可以读取创意组，但执行前必须同时满足：

1. 创意组响应 `can_deliver=true`；
2. 每条 `materials[]` 响应 `can_deliver=true`；
3. 每条 `selected_version_upload_status` 的真实值为 `uploaded`；
4. 使用 `effective_version_id` 作为本次执行锁定的内部版本，并在平台写入前再次读取校验；
5. 平台素材映射另存应用级映射表，不回填创意组或素材核心表。

任何 `pending_upload`、`failed`、缺失版本、暂停的应用素材或已归档主档都允许保留草稿，但响应
`can_deliver=false` 并在 `blocking_reasons` 中给出原因。调用方不得把“草稿保存成功”解释为可投放。
