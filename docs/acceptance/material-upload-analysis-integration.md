# 组合验收记录：素材上传、存储与素材/剧目分析

> 本记录遵守 [`../acceptance-standard.md`](../acceptance-standard.md)。本次验收只发生在本地隔离环境，不代表测试环境、生产环境或真实云存储已完成。

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 集成范围 | `0011 素材上传与存储` + `0012 素材与剧目分析` |
| 分支 | `codex/adsmind-10-insights-automation-integration` |
| 统一基线 | `cabd136049521e30a55c2df885f95522f90ea1a6` |
| Commit SHA | `4fa833caa64e48c3013e4e461a7181217ea38378`（最终集成候选） |
| 验收日期 | `2026-10-21` |
| 验收环境 | 前端 `127.0.0.1:4013`；后端 `127.0.0.1:8013`；隔离 MySQL 8.4.11 `127.0.0.1:3312`；本地文件存储 `/private/tmp/adsmind-integration-mysql-run-01a15d65/storage` |
| 验收角色 | 上传 owner、分析 viewer、同租户无应用身份用户、跨租户 owner |
| 当前等级 | `L3` |
| 允许描述 | `开发完成` |

## 1. 范围

### 本次完成

- 从统一基线按顺序集成 0011，再集成 0012；两个功能的路由、菜单、服务和测试同时存在，无合并冲突。
- 0011 提供租户/应用范围内的素材主档、版本、本地对象存储、直传/分片会话、校验、重试、幂等和审计。
- 0012 提供只读的素材/剧目分析，支持日期、平台、账户、覆盖状态、搜索、分页、详情和剧目汇总；不完整数据不伪装为 0 或 ROI。
- 组合验收中关闭前端权限一致性问题：viewer 仍可读取素材，但不再展示创建、编辑、关联、上传或失败重试入口；服务端写权限仍独立校验。

### 明确不包含

- 未 push、merge、deploy，未访问或修改生产/共享数据库，未调用广告平台写接口。
- 未接入真实 S3-compatible/OSS；云适配器只保留配置契约，本次使用本地隔离存储。
- 未改变既有信息架构；0012 继续使用临时分析菜单入口。

### 基线与集成顺序

1. `cabd136`：统一验收标准基线。
2. 0011：`f968f7e`（功能）、`04afa1b`（验收记录）。
3. 0012：`74c8db2`（功能）、`dc5ab68`（记录）、`109ee47`（真实验收测试）、`b6bdfe9`（L3 记录）。
4. `4fa833c`：组合验收发现的权限展示修正与格式清理。

0011/0012 分支中重复携带的验收标准提交与 `cabd136` 内容相同，未重复应用。当前迁移保持单线 `0001`–`0011`；0012 没有新增迁移。

## 2. 真实 HTTP 与数据库验收

真实 HTTP 专项执行结果：`Ran 3 tests ... OK`。

| 场景 | 实际状态与结果 | 数据库/副作用核对 | 结果 |
| --- | --- | --- | --- |
| 上传正常路径 | owner 创建素材与版本，prepare、传输、complete 成功；版本为 `uploaded` | 大小、MIME、SHA-256、storage key 和本地对象一致；审计含 `prepared`、`bytes_received`、`verified` | 通过 |
| 上传校验失败 | 非法输入 422；SHA 不一致时会话/版本进入 `failed` | 不伪造 `uploaded`；失败审计可回读 | 通过 |
| 上传鉴权与隔离 | 未登录 401、viewer 403、跨应用/跨租户资源 404 | 被拒请求不改变目标记录 | 通过 |
| 上传幂等 | 重复 prepare/complete 返回同一业务结果 | 不重复创建有效会话或版本 | 通过 |
| 分析正常路径 | owner/viewer 200；52 条素材，第 1 页 50、第 2 页 2；完整素材 spend=10、revenue=20、ROI=2 | scope 为目标 tenant/application；分析请求前后数据与 `app_oplog` 指纹不变 | 通过 |
| 分析参数与权限 | 未登录 401；缺日期、反向日期、非法分页 422；无应用身份 403 | 无分析写入 | 通过 |
| 分析隔离 | 同租户其他应用及跨租户均为 200/空集合 | 不泄漏原应用 52 条数据 | 通过 |
| 分析筛选与汇总 | 搜索、平台、账户、覆盖状态、分页、素材/剧目维度均符合预期；部分覆盖的剧目 ROI 为 `null` | 只读取精确账户与素材映射链 | 通过 |
| 分析依赖失败 | 临时移走隔离 BIZ 事实表返回 500；恢复后重新 200 | 表在 `finally` 中恢复，无业务写入 | 通过 |

最终数据库回读：

- 浏览器素材 `Integration browser material` 为 revision `2`、版本 `v1 uploaded/local`、114 bytes、SHA 前缀 `a71e7e86b175`。
- 上传证明素材保留 `v1 uploaded`、`v2 failed`、浏览器重试产生的 `v3 uploaded`；刷新后页面与数据库一致。
- 隔离库审计汇总可见 `prepared`、`bytes_received`、`verified` 和 `failed` 状态转换。
- 分析相关 `app_oplog` 为零，重复 GET 响应稳定。

## 3. 浏览器点击验收

| 角色/页面 | 实际流程与结果 | Network / Console | 结果 |
| --- | --- | --- | --- |
| owner `/materials/upload` | 菜单进入、创建、编辑、选择真实 fixture、上传、失败版本重试、刷新回读均完成；owner 写入口仍可见 | create/edit/prepare/upload/complete 走真实 `8013`；无未处理 error | 通过 |
| viewer `/materials/upload` | 页面显示明确只读提示；创建、编辑、版本、关联、解除关联、重试入口均隐藏 | 读取 200；服务端写入专项为 403；无未处理 error | 通过 |
| viewer `/asset-analysis` | 显示 52 条、映射 3/5、事实 3/4；可分页、搜索、组合筛选、切换剧目维度并打开详情 | GET 200；无写请求、无未处理 error | 通过 |
| 分析空态 | 完整覆盖 + 剧目维度组合显示“不代表指标为 0”的空态 | GET 200/空列表 | 通过 |
| 分析错误与恢复 | 临时中断隔离 BIZ 依赖后显示“服务器内部错误”；恢复并刷新后回到 52 条 | 500 后恢复 200 | 通过 |

Console 只有 React Router future flag 与无头浏览器中 Recharts 初始容器尺寸 warning，没有 error。页面、接口和数据库回读一致。

## 4. 租户、应用和角色隔离

| 检查项 | 实际结果 | 结果 |
| --- | --- | --- |
| 跨租户 | 上传对象返回安全 404；分析返回当前跨租户 scope 的空集合 | 通过 |
| 同租户跨应用 | 上传对象返回安全 404；分析返回当前应用 scope 的空集合 | 通过 |
| owner/editor 写权限 | owner 浏览器创建、编辑、上传和重试完成 | 通过 |
| viewer 只读 | 前端隐藏写入口并显示只读提示；直接写 API 为 403；分析 GET 可读 | 通过 |
| 无应用身份 | 分析 API 为 403，不能通过直接路由扩大授权 | 通过 |
| 服务端边界 | 前端隐藏不替代服务端鉴权；所有上传资源查询同时约束 tenant/application | 通过 |

## 5. 数据库迁移

| 检查项 | 实际结果 | 结果 |
| --- | --- | --- |
| 全新数据库升级 | 空库顺序应用 `0001_legacy_baseline` 至 `0011_material_uploads` | 通过 |
| 已有基线升级 | `0010` 后只应用 `0011_material_uploads` | 通过 |
| 回滚上一版本 | 回滚 `0011_material_uploads`，历史停在 `0010_automation_rules` | 通过 |
| 再次升级 | 重新应用 `0011_material_uploads` | 通过 |
| 最终迁移头 | 实库历史精确为 `0001`–`0011`，单线 11 项 | 通过 |
| 组合兼容 | 0012 无迁移；读取当前 `0011` schema 正常 | 通过 |

## 6. 自动化检查

| 检查 | 通过 | 失败 | 跳过 | 结果/说明 |
| --- | ---: | ---: | ---: | --- |
| 后端完整回归 | 136 | 0 | 3 | `Ran 139 tests ... OK (skipped=3)`；跳过的是需运行服务的 HTTP 套件 |
| 真实 HTTP 专项 | 3 | 0 | 0 | 上述 3 项跳过测试连接真实 `8013` 后全部通过 |
| 前端完整测试 | 40 | 0 | 0 | `5 files / 40 tests passed` |
| TypeScript | — | — | — | `tsc -b` 通过 |
| 修改范围 ESLint | — | — | — | 集成涉及的 7 个 TS/TSX 文件通过 |
| 生产构建 | — | — | — | Vite build 通过；2491 modules，保留 bundle size warning |
| 差异格式 | — | — | — | `git diff --check` 通过 |

## 7. 缺陷与遗留

| 编号 | 等级 | 问题 | 影响 | 状态/计划 |
| --- | --- | --- | --- | --- |
| `FIX-INT-001` | P2（已关闭） | viewer 页面曾展示素材写入口，点击后由服务端 403 | 权限提示不一致，但无权限绕过 | `4fa833c` 隐藏写入口并完成 owner/viewer 浏览器复验 |
| `UI-001` | P2 | 无头浏览器中 Recharts 初始尺寸 warning | 图表数据与交互正常，无 Console error | 后续为图表容器增加显式最小尺寸 |
| `UI-002` | P3 | React Router future flag warning | 仅升级提示 | 路由升级时统一处理 |
| `BUILD-001` | P3 | 生产 bundle 超过 500 kB | 不影响功能正确性 | 后续统一拆包 |

- 未关闭 P0/P1：`0/0`
- 未关闭 P2/P3：`1/2`

## 8. 验收证据索引

- 上传 HTTP：`backend/tests/test_material_uploads_http.py`；上传实库：`backend/tests/test_material_uploads_mysql.py`。
- 分析 HTTP：`backend/tests/test_asset_analysis_http.py`；聚合规则：`backend/tests/test_asset_analysis.py`。
- 浏览器实现：`frontend/src/features/material-catalog/MaterialCatalogPage.tsx`、`frontend/src/pages/AssetAnalysisPage.tsx`。
- 迁移：`backend/migrations/runner.py`、`backend/migrations/versions/v0011_material_uploads.py`。
- 命令输出、浏览器 DOM/Console、HTTP access log 与数据库回读保存在本次 Codex Session；未保存生产数据或秘密信息。

## 9. 未完成项和下一步

1. 提升 L4 前，需要明确授权的沙箱/测试环境与真实 S3-compatible/OSS 凭据，验证 multipart、超时、失败恢复和对象生命周期。
2. 推送、合并、部署与生产验收均未执行；如需进行，应另行授权并使用届时的目标基线重新验证。
3. 0012 的临时菜单入口后续应随统一信息架构收敛，但不阻塞当前 L3。

## 10. 最终结论

```text
当前等级：L3
允许描述：开发完成
未达到下一等级的原因：未在授权的沙箱/测试环境连接真实云存储等外部依赖完成端到端验收
P0/P1：0/0
P2/P3：1/2
下一步：取得明确授权与测试凭据后，再执行 L4 外部依赖与失败恢复验收
```

外部影响：无生产数据库、无真实平台写、无发布、无部署。

验收人：`Codex Session integration`
验收日期：`2026-10-21`
