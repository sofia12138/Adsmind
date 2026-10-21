# 应用级广告创建草稿

此模块只负责把当前应用的账户组、命名规则和创意组解析成 AdsMind 内部草稿。它不会调用 Meta、TikTok、YouTube 或其他平台的创建、上传、推送、审核、预审核接口。

## 生命周期

- `DRAFT`：可以编辑。每次更新必须携带当前 `revision`，旧版本返回 `409`。
- `READY`：就绪检查通过后冻结。草稿和 `execution_snapshot` 均不可再修改。
- `request_key` 在 `tenant_id + application_id + created_by` 范围内幂等；同一编号配不同内容返回 `409`。

创建和更新会保存当时的账户解析、名称预览、创意组素材解析及每条素材的 `effective_version_id`。`check` 与 `ready` 会重新读取真实的应用资源，而不是信任之前保存的结果。

## API

- `GET /api/ad-creation-drafts`
- `POST /api/ad-creation-drafts`
- `GET /api/ad-creation-drafts/{id}`
- `PUT /api/ad-creation-drafts/{id}`
- `POST /api/ad-creation-drafts/{id}/check`
- `POST /api/ad-creation-drafts/{id}/ready`
- `GET /api/ad-creation-drafts/{id}/execution-snapshot`

读操作要求当前应用的 `owner/admin/editor/viewer`；写操作要求 `owner/admin/editor`。所有仓储查询都由已验证的 `tenant_id + application_id` 作用域限定。创建、更新和标记就绪写入操作日志。

## 下一阶段执行边界

平台执行器只应读取 `READY` 草稿的快照端点。响应包含：

- `contract: ad_creation_execution_snapshot.v1`
- 草稿来源版本与 `tenant_id + application_id`
- 已重新验证的账户集合
- 命名规则和逐账户名称预览
- 创意组及素材 `effective_version_id` / 上传状态
- 快照 `sha256`
- `external_write_authorized: false`

`external_write_authorized: false` 是明确边界：快照本身不是平台写入授权。后续执行阶段必须有独立权限、审批、平台幂等和执行审计设计，不能把本模块的“准备就绪”解释成“已创建”或“可自动发布”。
