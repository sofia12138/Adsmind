# 素材系统核心接口契约（0006，0011 扩展）

## 范围

- `material_masters`、`material_versions` 是租户级资源，可选关联同租户 `drama_masters`。
- `app_application_materials` 只保存某应用对素材及版本策略的选择，不复制主档，也不代表平台素材。
- 平台素材映射、平台推送、预审核和转码仍不在本契约范围；0011 新增的本地验证上传及云配置边界见 [素材上传与存储契约](material-upload-contract.md)。
- 默认存储后端为 `unconfigured`。版本登记成功只表示元数据已持久化，`upload_status` 必须保持
  `pending_upload`，`upload.available=false`，不得解释为文件上传成功。

## HTTP 接口

所有接口要求已验证 JWT 租户作用域；应用引用接口还要求已验证的 `X-Application-Id`。
跨租户素材、跨租户剧目、同租户另一应用的引用和错误的固定版本统一返回 404。

| 方法 | 路径 | 作用域 | 用途 |
| --- | --- | --- | --- |
| GET/POST | `/api/material-catalog/masters` | tenant | 列表、新建主档 |
| GET/PUT | `/api/material-catalog/masters/{id}` | tenant | 详情（含版本）、乐观锁更新 |
| GET/POST | `/api/material-catalog/masters/{id}/versions` | tenant | 版本列表、文件元数据登记 |
| GET/POST | `/api/material-catalog/references` | tenant + application | 当前应用选择列表、添加选择 |
| PATCH/DELETE | `/api/material-catalog/references/{material_id}` | tenant + application | 修改或移除当前应用选择 |

主档更新必须传当前 `revision`。版本不可覆盖；版本号在锁定主档行后递增。版本登记至少要求
`source_filename`、`mime_type`、正数 `size_bytes`，可带 SHA-256、尺寸、时长和扩展元数据。

## 后续创意组依赖的稳定字段

创意组只应保存应用级素材引用或消费以下响应，不应直接把租户素材 ID 当作平台素材 ID：

- `material_id`：租户素材主档 ID；所有读取仍必须带服务端验证的租户作用域。
- `selection_mode`：`latest` 或 `pinned`。`latest` 时 `selected_version_id=null`；`pinned` 时必须提供
  属于同一租户、同一素材的版本 ID。
- `reference_status`：`selected` 或 `paused`。
- `latest_version_number`、`selected_version_number`：用于界面说明，不是平台版本号。
- `selected_version_upload_status`：创意组在消费文件前必须确认真实值为 `uploaded`；缺失或
  `pending_upload` 不能降级为可用。

未来平台映射应新增独立应用级表，至少以
`(tenant_id, application_id, material_id, version_id, platform, account_id)` 定位，并在执行前再次确认
版本确实已上传；不得向当前三张核心表回填平台执行状态。

应用级创意组对上述字段的具体消费与阻断规则见
[应用级创意组接口契约](creative-groups-contract.md)。
