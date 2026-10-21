# 自动化规则评估契约

自动化规则属于当前租户和应用，只用于读取 AdsMind 内部状态并生成需要人工处理的建议或阻断原因。规则评估不是调度器，也不是广告平台执行器。

## 安全边界

- 每次评估固定保存 `dry_run=true`、`external_write_authorized=false`，数据库约束禁止改成可执行状态。
- 规则只允许读取白名单中的素材、创意组、广告草稿和平台预检字段；不接受任意 SQL、表达式或外部请求。
- 建议结果固定为 `review_required`，不会修改草稿、标记 READY、上传素材、创建广告、调整预算或发送通知。
- 规则、版本、评估、建议和审计记录均按 `tenant_id + application_id` 限定；越界对象表现为不存在。
- 同一规则版本和规范化输入快照生成稳定的评估键，重复试跑复用原评估记录。

## API

- `GET /api/automation-rules`：列出当前应用的规则。
- `POST /api/automation-rules`：创建规则和首个不可变版本。
- `GET /api/automation-rules/{rule_id}`：读取规则、历史版本和审计。
- `PUT /api/automation-rules/{rule_id}`：使用 `expected_version` 创建新版本。
- `POST /api/automation-rules/{rule_id}/evaluations`：对明确选择的内部对象进行 dry-run。
- `GET /api/automation-rules/{rule_id}/evaluations`：列出规则评估记录。
- `GET /api/automation-rules/evaluations/{evaluation_id}/detail`：读取评估、建议、阻断原因和审计。

## 未来执行边界

若未来需要自动执行，必须建立独立的执行契约、审批和调度入口。执行入口不得复用当前评估记录作为平台写入授权，并应重新校验对象状态、权限、幂等键和平台侧结果。
