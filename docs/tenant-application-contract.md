# 租户与应用隔离契约（第 0 阶段）

本文是后续剧目库、素材库、广告资产和投放能力的强制接口约定。`tenant_id` 与
`application_id` 不是可选的展示字段，而是服务端授权和数据查询边界。

## 1. 作用域层级

### 租户级

- 用户、租户成员、剧目主档、原始素材主档、平台凭证密文、套餐与配额；
- 可在同一租户的多个应用间复用；
- 所有唯一性、内容指纹和去重必须至少包含 `tenant_id`，禁止跨租户根据文件散列、
  名称、平台编号或对象地址合并记录，也禁止返回“另一租户已存在”的可识别信息。

### 应用级

- 广告账户绑定、账户组、创意组、命名规则、广告草稿、平台执行记录；
- 所有主键读取、列表、更新和删除必须同时带 `tenant_id` 与 `application_id`；
- 关联租户级剧目/素材时，先验证资源的 `tenant_id` 与当前租户相同，再创建应用级引用。

平台凭证密文本身是租户级数据，但读取凭证前必须经由当前应用拥有的广告账户。不能用
`tenant_id + platform` 任取一条凭证，也不能从环境变量为已绑定请求补全客户凭证。

## 2. 服务端上下文

- HTTP 请求只信任验签后的 JWT；`X-Tenant-Id` 不能覆盖 JWT 租户。
- `X-Application-Id` 只用于在已验证租户内选择应用。服务端必须再次校验应用归属、状态，
  以及普通租户成员的应用成员关系。租户 owner/admin 可管理本租户全部应用。
- 数据层只读取 `core.isolation.current_scope`。没有显式作用域时必须失败，禁止默认到
  internal tenant 或默认应用。
- OAuth 回调只从签名 state 恢复租户/应用，并再次校验二者关系和状态。

## 3. 数据访问接口

新 repository/service 应采用以下形状，不接受客户端直接传入未经验证的作用域：

```python
def get_tenant_asset(asset_id: str, *, scope: Scope) -> Asset | None: ...
def list_application_drafts(*, scope: Scope, page: int) -> Page[Draft]: ...
def attach_asset(asset_id: str, *, scope: Scope) -> ApplicationAsset: ...
```

- 租户级查询条件：`WHERE tenant_id = :tenant_id`。
- 应用级查询条件：`WHERE tenant_id = :tenant_id AND application_id = :application_id`。
- 更新/删除的受影响行数为 0 时返回 404，不做无作用域的第二次查询来区分“存在但无权”。
- 应用级表应使用 `(tenant_id, application_id, ...)` 索引；可行时添加复合外键到
  `app_applications(id, tenant_id)`，由数据库同时保证应用归属。
- 禁止用字符串拼接接受租户/应用参数。现有 `tenant_cursor` 仅支持列明的简单单表 CRUD，
  复杂查询必须显式写出作用域条件并单独测试。

## 4. 缓存、文件与后台任务

- 应用级缓存/锁：`<namespace>:tenant:<tid>:application:<aid>:...`；租户级缓存至少包含
  `tenant:<tid>`。禁止只用记录 id、用户名、平台或账号 id。
- 对象路径：`<namespace>/tenants/<tid>/applications/<aid>/...`；租户级对象可省略
  applications 段。路径片段必须拒绝 `/`、`\\`、`.` 与 `..`。
- 临时上传文件也放入作用域目录并在 `finally` 删除。外部对象存储键沿用同一前缀。
- 队列消息必须携带不可变的 `tenant_id` 和 `application_id`；worker 在执行前重新校验
  租户/应用状态，绑定 `Scope` 后才调用 repository、缓存或凭证服务。
- 周期任务必须枚举明确的活跃应用，不允许无上下文运行后隐式使用 internal tenant。
  分布式部署时，任务锁也必须使用上述应用级缓存键。

## 5. 后续业务最低验收

剧目库和素材库需要同时覆盖：跨租户按 id/散列/搜索词不可见；同租户跨应用可引用；
应用引用删除不删除租户主档；去重只在租户内发生。

广告账户、账户组、创意组、命名规则、草稿和执行记录需要同时覆盖：跨租户拒绝；同租户
另一应用拒绝；当前应用合法读写；更新/删除不能通过猜测 id 影响其它作用域；后台任务、
缓存和对象路径与 API 得到相同隔离结果。

## 6. 数据库迁移

应用启动只做只读结构检查，缺少结构时直接失败，不执行 `CREATE/ALTER/DROP` 或数据回填。
运维人员必须先查看计划，并在备份和维护窗口内显式执行：

```bash
cd backend
python -m migrations.cli plan
python -m migrations.cli upgrade
```

`0001_legacy_baseline` 接管历史启动建表和回填，因为回滚意味着删除既有业务表，所以只能从
执行前备份恢复。`0002_scope_foreign_keys` 在检查无孤立记录后添加应用/租户复合外键，支持
`python -m migrations.cli downgrade` 回滚最近一版。MySQL DDL 会隐式提交；执行中断时必须先
核对约束和 `app_schema_migrations`，不能盲目重跑或手工伪造版本。
