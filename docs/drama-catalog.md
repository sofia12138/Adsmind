# 剧目库

剧目库采用“租户主档 + 应用引用”两层模型，不复用内部数据分析插件的剧级事实表。

## 数据边界

- `drama_masters` 是租户级主档。读取、搜索、更新、删除和去重均显式包含
  `tenant_id`；标准化剧名和内容指纹的唯一键也包含 `tenant_id`。
- `app_application_dramas` 是应用级引用。所有 CRUD 同时包含 `tenant_id` 与
  `application_id`，并通过复合外键保证应用和主档都属于同一租户。
- 同一租户的多个应用可以引用同一主档。解除应用引用不删除主档；仍被任意应用引用的
  主档不能删除。
- 越权或不可见的主档、引用统一按不存在处理，不执行无作用域的二次查询。

## API

- `GET/POST /api/drama-catalog/masters`
- `GET/PUT/DELETE /api/drama-catalog/masters/{id}`
- `GET/POST /api/drama-catalog/references`
- `PATCH/DELETE /api/drama-catalog/references/{drama_id}`

租户和应用都只来自服务端验证后的请求作用域。客户端不能通过请求参数指定租户；应用由
经过归属和成员关系校验的 `X-Application-Id` 选择。

## 迁移与回滚

`0004_drama_catalog` 先创建主档表，再创建引用表；回滚按相反顺序删除。应用启动只做只读
结构检查，不自动执行迁移。部署前必须先审查计划并在专用环境显式执行：

```bash
cd backend
python -m migrations.cli plan
python -m migrations.cli upgrade
```

如需回滚最近一版，使用 `python -m migrations.cli downgrade`。本次开发未执行任何数据库
迁移、生产连接或真实平台写入。
