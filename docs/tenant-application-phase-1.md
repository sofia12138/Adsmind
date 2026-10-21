# 租户/应用隔离第 1 阶段范围与下一阶段接口

本阶段只改造本地代码和专用测试数据库，不包含部署、生产数据库、平台写入、push 或 merge。
隔离语义以 `tenant-application-contract.md` 为准。

## 已覆盖的数据访问边界

### 租户级

- 投放模板、落地页、文案包、地区组和 TikTok 素材上传记录继续使用 `tenant_id`；
- 主键读取、列表、更新、删除均通过 fail-closed 的租户游标；
- 同租户不同应用可复用这些主档，跨租户按 id 不可见。

### 应用级

- 广告账户的插入、主键读取、列表、更新、删除和默认账户修改统一使用
  `tenant_id + application_id`，不再保留默认应用的全租户读取例外；
- 广告系列、广告组、广告和归一化报表按当前应用拥有的广告账户显式过滤；写入前先验证
  每个 `platform + account_id` 均属于当前应用；
- 广告草稿、发行频道和发行草稿的读取与更新显式包含两个作用域字段；广告草稿执行状态、
  checkpoint 和最终结果不能只按主键更新；
- 新增账户组、创意组、命名规则、平台执行记录 repository。它们目前是数据层契约，尚未
  接入产品路由和页面，不能声称功能已经可用。

### 不在本阶段改造的范围

- `biz_ops_*`、归因、优化师和剧目分析等内部数据源仍由 internal-tenant 路由门禁保护；
- 账户级平台结构和日报仍保留原表结构，通过广告账户归属过滤，不把 `tenant_id` 和
  `application_id` 重复写入每一行；
- 平台真实写入、真实 OAuth、生产迁移和部署均未执行。

## 迁移

`0003_application_resources` 创建四个应用级表，并对每张表添加
`(tenant_id, application_id, ...)` 索引及到 `app_applications(id, tenant_id)` 的复合外键。
启动 guard 要求这些表与作用域列完整存在；`0001` 的阶段内 guard 只检查其自身负责的基线，
避免未来迁移的表反向阻断基线执行。`0002`、`0003` 均支持逐步回滚；`0001` 仍只能从备份恢复。

## 下一阶段：剧目库接口契约

剧目库从租户级主档开始，应用只保存引用和投放配置，禁止为每个应用复制主档：

```python
def create_drama_master(*, title: str, aliases: list[str], scope: Scope) -> Drama: ...
def get_drama_master(drama_id: int, *, scope: Scope) -> Drama | None: ...
def search_drama_masters(query: str, *, scope: Scope, page: int) -> Page[Drama]: ...
def update_drama_master(drama_id: int, changes: dict, *, scope: Scope) -> Drama | None: ...
def delete_drama_master(drama_id: int, *, scope: Scope) -> bool: ...

def attach_drama(drama_id: int, *, scope: Scope) -> ApplicationDrama: ...
def list_application_dramas(*, scope: Scope, page: int) -> Page[ApplicationDrama]: ...
def update_drama_settings(drama_id: int, changes: dict, *, scope: Scope) -> ApplicationDrama | None: ...
def detach_drama(drama_id: int, *, scope: Scope) -> bool: ...
```

- `drama_masters`：租户级，唯一性、别名和内容指纹至少包含 `tenant_id`；
- `app_application_dramas`：应用级，主键和唯一键包含 `tenant_id + application_id + drama_id`；
- `attach_drama` 先验证主档 `tenant_id`，再创建应用引用；detach 不删除主档；
- 搜索、按 id 读取、更新、删除、去重全部覆盖跨租户测试；引用 CRUD 同时覆盖同租户跨应用测试；
- API 对越权 id 统一返回 404，不做第二次无作用域查询；列表不接受客户端传入 tenant id；
- 剧集、语言版本、成片和素材引用在进入实现前先明确是租户主档还是应用配置，不能混用。
