# 素材上传与存储契约（0011）

## 边界

- 本功能把 `material_versions` 的文件从 `pending_upload` 推进到经验证的 `uploaded`，不执行 TikTok、Meta、YouTube 或其他平台推送。
- 所有上传会话、分片和审计记录都以服务端验证后的 `tenant_id + application_id` 查询；客户端传入的资源 ID 不能扩大范围。
- 默认 `local` 适配器仅用于本地开发。`s3-compatible` / `oss` 只定义配置接口；当前代码不导入云 SDK、不签发真实云 URL、也不连接真实云账户。
- `uploaded` 只在对象存在且实际大小、检测 MIME、SHA-256 全部与登记版本一致后写入。登记元数据、收到部分字节或完成回调本身均不代表成功。

## 状态机

`prepared -> uploading -> uploaded`

失败分支为 `failed`，超时分支为 `expired`。失败或过期会话可显式重试；重试递增 `attempt_count`。完成回调使用应用范围内唯一的 `idempotency_key`，重复完成已验证会话返回同一结果，不重复改变版本或审计成功状态。

## HTTP API

所有接口要求 JWT、素材库权限及已验证的当前应用；写接口仅允许 `super_admin`、`admin`、`optimizer`、`designer`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/material-uploads/prepare` | 为现有素材版本准备直传或分片会话 |
| `GET` | `/api/material-uploads` | 列出当前应用的上传会话 |
| `GET` | `/api/material-uploads/{upload_id}` | 回读状态、进度与分片 |
| `PUT` | `/api/material-uploads/{upload_id}/content` | 本地开发直传字节 |
| `PUT` | `/api/material-uploads/{upload_id}/parts/{part_number}` | 本地开发上传单个分片 |
| `POST` | `/api/material-uploads/{upload_id}/complete` | 幂等完成并执行服务端验证 |
| `POST` | `/api/material-uploads/{upload_id}/retry` | 重置失败/过期会话以重试 |

准备请求使用已登记版本中的 `size_bytes`、`mime_type`、`checksum_sha256` 作为不可由完成回调覆盖的期望值。SHA-256 缺失时拒绝准备。响应不返回内部 `storage_key`，只返回当前应用可调用的上传入口。

## 存储配置接口

| 环境变量 | 说明 |
| --- | --- |
| `MATERIAL_STORAGE_BACKEND` | `local`（可写）或 `s3-compatible` / `oss`（配置契约，当前不可写） |
| `MATERIAL_STORAGE_LOCAL_ROOT` | 本地私有对象根目录 |
| `MATERIAL_STORAGE_MAX_BYTES` | 单个登记文件上限 |
| `MATERIAL_UPLOAD_SESSION_TTL_SECONDS` | 会话有效期 |
| `MATERIAL_UPLOAD_PART_SIZE_BYTES` | 分片大小 |
| `MATERIAL_STORAGE_ENDPOINT/REGION/BUCKET` | S3-compatible/OSS 定位配置 |
| `MATERIAL_STORAGE_ACCESS_KEY_ID/SECRET` | 预留凭据接口；不得提交真实值 |
| `MATERIAL_STORAGE_PATH_STYLE` | S3-compatible 路径风格开关 |

本地对象键由服务端按 `tenant/application/material/version/upload` 分层生成，并在解析绝对路径时阻止越过配置根目录。

## 平台推送消费契约

后续平台推送只能消费满足以下全部条件的版本：

1. `material_versions.upload_status = 'uploaded'`；
2. `storage_backend` 与 `storage_key` 非空；
3. 对应成功会话与消费方具有相同 `tenant_id + application_id`；
4. 推送前重新确认对象仍存在，不能只依赖历史 UI 状态；
5. 平台映射另存应用级表，至少以 `(tenant_id, application_id, material_id, version_id, platform, account_id)` 唯一定位；
6. 平台返回状态、平台素材 ID、审核结果不得覆盖本地上传会话或素材版本的文件验证事实。

推送方不得消费 `pending_upload`、`uploading`、`failed`、`expired` 或未知状态，也不得把 dry-run、预检通过或上传准备成功解释为平台已接收。
