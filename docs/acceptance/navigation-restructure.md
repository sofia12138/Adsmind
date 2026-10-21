# 功能验收记录：AdsMind 导航重构

> 本记录遵守 [`../acceptance-standard.md`](../acceptance-standard.md)。本次验收只发生在本地隔离环境，不代表测试环境、生产环境或真实外部平台已完成。

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 功能编号 | `NAV-RESTRUCTURE` |
| 功能名称 | AdsMind 导航重构 |
| 分支 | `codex/adsmind-10-insights-automation-integration` |
| 统一基线 | `b7f0257f93fa07a342e9abad960c4a1b1d79a293` |
| 功能 Commit | `8f51265` |
| 验收日期 | `2026-10-21` |
| 验收环境 | 前端 `127.0.0.1:4021`；后端 `127.0.0.1:8021`；隔离 MySQL 8.4.11 `127.0.0.1:3312`；APP/BIZ/PRD 分别为 `adsmind_nav_app`、`adsmind_nav_biz`、`adsmind_nav_prd` |
| 浏览器尺寸 | 窄屏 `319 × 778`；桌面 `2091 × 1176` |
| 验收角色 | internal super_admin、租户 owner、租户 admin、普通成员/editor、viewer/无面板权限 |
| 当前等级 | `L3` |
| 允许描述 | `开发完成` |

## 1. 范围

### 已完成

- 按最终信息架构固定 10 个一级入口/分组、49 个节点及顺序。
- “账户组”“命名规则”移动到“广告资产库”，各只显示一次。
- 从导航隐藏“广告草稿”“平台执行预检”“模板管理”“TikTok 素材上传”；页面、路由、接口和权限键保留。
- 收敛统一基线中后集成的“素材与剧目分析”临时菜单入口；`/asset-analysis` 页面、接口和权限继续保留并完成回归。
- 保留所有现有 `path`、`panelKey`、`pluginKey`、`internalOnly`、外部链接和 `/ads/create-tiktok-minis` 查询参数透传。
- 修复 `/ads/create` 同时高亮“广告数据”和“新建广告”的问题。
- 修复菜单宽度加外边距导致的横向溢出；增加长文案截断和横向隐藏。
- 分组按钮增加 `aria-expanded`、`aria-controls`，支持 Enter/Space；路由进入分组时自动展开并把选中项滚动到可见区域。
- 将最终架构与迁移映射落入业务仓库：`docs/navigation-architecture.md`、`docs/navigation-migration-map.md`。

### 明确不包含

- 未删除或放宽任何服务端鉴权、业务接口、页面或数据库对象。
- 未改变素材上传、素材/剧目分析或其他业务页面语义。
- 未 push、merge、deploy；未连接生产、共享数据库或真实广告平台；未执行平台写入。

## 2. 导航与路由验收

| 场景 | 实际结果 | 结论 |
| --- | --- | --- |
| 一级顺序与数量 | super_admin 展示 2 个直接入口 + 8 个分组；展开后 41 个链接 + 8 个分组 = 49 节点，顺序与确认稿一致 | 通过 |
| 移动入口 | “广告资产库”顺序为落地页、文案、地区组、账户组、命名规则；账户组/命名规则各 1 次，系统管理不重复 | 通过 |
| 四个隐藏入口 | 所有角色导航中均不显示；super_admin 原 URL 均可加载原页面 | 通过 |
| 临时分析入口收敛 | 菜单不显示；`/asset-analysis` 加载“素材与剧目分析”页面，真实 API 为 200 | 通过 |
| 原权限保留 | 隐藏入口统一由 `preservedDirectRoutes` 带原 `panelKey` 注册；viewer 直接访问 `/ads/create` 跳转 `/forbidden` | 通过 |
| TikTok Minis 旧链接 | `/ads/create-tiktok-minis?template_id=42&source=minis` 跳转为 `/ads/create?template_id=42&source=minis` | 通过 |
| 唯一选中态 | `/ads/create` 的 `aria-current=page` 只有“新建广告”；“广告数据”不再同时选中 | 通过 |
| 详情选中 | `/ads/app-drafts/:id` 仅由显式 `matchSubpaths` 继承“应用广告草稿” | 自动化通过 |
| 刷新/返回/前进 | 账户组页面刷新后仍唯一选中；返回首页、前进后重新选中并展开广告资产库 | 通过 |
| 应用切换 | owner 从“Navigation Acceptance App”切换到“Navigation Second App”，页面刷新后选择器、首页文案和菜单均对应新应用 | 通过 |
| 键盘 | “广告资产库”使用 Enter 展开、Space 收起、Enter 再展开；ARIA 状态同步为 true/false/true | 通过 |

## 3. 角色、插件与内部入口

| 身份 | 实际结果 | 结论 |
| --- | --- | --- |
| internal super_admin | 运营数据、套餐升级审批及 drama/optimizer/designer 插件入口可见；49 节点完整 | 通过 |
| 租户 owner | 9 个可见一级入口/分组（无运营数据）；`core_ads` 以外插件入口全部隐藏；账户组/命名规则可见 | 通过 |
| 租户 admin | 结构与 owner 的面板权限一致；账户组原 URL 加载并请求真实接口 200 | 通过 |
| 普通成员/editor | 仅保留 optimizer 角色允许且 `core_ads` 插件可用的分组；`/materials/upload` 可加载 | 通过 |
| viewer/无面板权限 | 菜单仅“首页概览”；直接访问 `/ads/create` 进入 `/forbidden` | 通过 |
| 插件开关 | internal 租户显示 drama/optimizer/designer；外部租户只启用 `core_ads`，对应四个插件入口均不渲染 | 通过 |
| 服务端独立鉴权 | 素材上传真实 HTTP 覆盖未登录 401、viewer 403、跨应用/跨租户 404；分析覆盖未登录 401、无应用身份 403 和跨 scope 空集合 | 通过 |

前端菜单变更没有修改任何后端文件。服务端鉴权继续独立执行，前端隐藏不改变接口结果。

## 4. 桌面、窄屏、滚动与可访问性

| 检查 | 窄屏 319px | 桌面 2091px | 结论 |
| --- | ---: | ---: | --- |
| aside `clientWidth / scrollWidth` | `220 / 220` | `220 / 220` | 无横向溢出 |
| nav `clientWidth / scrollWidth` | `214 / 214` | `214 / 214` | 无横向滚动 |
| 页面 `clientWidth / scrollWidth` | `319 / 319` | `2091 / 2091` | 无页面横向滚动 |
| 纵向菜单 | `clientHeight 531 / scrollHeight 1915`，`overflow-y:auto` | 可完整滚动 | 可触达 |
| 分组 ARIA | 8 个分组均有唯一 `aria-controls`，展开后目标元素存在，`aria-expanded=true` | 同左 | 通过 |
| Console error | 0 | 0 | 通过 |

通过自动滚动后的“新建广告”、页面底部的“账户组”以及应用切换器完成实际点击，没有发现点击死区或选中项不可触达。

## 5. 素材上传与素材/剧目分析关键回归

真实后端 `8021` 与隔离数据库上执行 3 个 HTTP 专项用例，全部通过：

| 功能 | 覆盖 | 实际结果 |
| --- | --- | --- |
| 素材上传 | 创建素材/版本、prepare、传输、complete、重复请求、校验失败、viewer、跨应用、跨租户、数据库回读 | 通过；上传成功状态、SHA、大小、审计与隔离符合原 L3 契约 |
| 素材/剧目分析 | owner/viewer、无应用身份、分页、搜索、剧目维度、跨 scope、零写入、依赖失败与恢复 | 通过；依赖失败测试产生预期 500，恢复后重新 200 |
| 浏览器 | 普通成员 `/materials/upload`；super_admin `/asset-analysis` | 页面加载、真实 GET 200、Console 无 error |

上述回归没有连接真实云存储或广告平台，仍属于本地 L3 证据，不提升原功能的 L4/L5。

## 6. 数据库与迁移

- 新建三座隔离空库后，从 `0001_legacy_baseline` 连续升级到 `0011_material_uploads`，共应用 11 个迁移。
- 本次导航重构没有数据库模型或迁移变更，因此回滚/再升级对本功能不适用。
- 完整实库回归使用该隔离三库；没有连接生产、共享或真实外部数据库。

## 7. 自动化检查

| 检查 | 通过 | 失败 | 跳过 | 实际结果 |
| --- | ---: | ---: | ---: | --- |
| 前端完整测试 | 50 | 0 | 0 | `8 files / 50 tests passed`；其中新增导航专项 10 个 |
| TypeScript | — | — | — | `tsc -b --pretty false` 通过 |
| 变更范围 ESLint | — | — | — | 10 个 TS/TSX 变更文件通过 |
| 生产构建 | — | — | — | Vite 8.0.3；2493 modules；构建通过 |
| 后端完整实库回归 | 136 | 0 | 3 | `Ran 139 tests ... OK (skipped=3)`；跳过项为需要运行中 HTTP 服务的专项 |
| 真实 HTTP 专项 | 3 | 0 | 0 | 连接 `127.0.0.1:8021` 后全部通过 |
| 差异检查 | — | — | — | `git diff --check` 通过 |

实库回归首次运行未注入 `ENCRYPTION_KEY_B64`，出现 5 error + 1 failure；补入仅供本地隔离测试进程使用的固定 32 字节测试密钥后，全套重跑为 136 通过、0 失败、3 跳过。该问题属于验收环境配置，不是本次代码缺陷。

## 8. Network 与 Console

- 浏览器覆盖的导航页面请求均命中真实 `8021` 后端；菜单点击、隐藏路由、账户组、素材上传、分析页和应用列表没有意外 404/500。
- HTTP 专项中的 401/403/404/422 和单次 500 均为明确的负向/依赖失败场景，随后恢复验证通过。
- 窄屏与桌面浏览器 Console error 均为 0。
- 外部租户首页会请求无权限的 `/api/insight/config` 并收到 403；页面已有降级处理、Console 无 error、导航流程不受阻，记录为遗留 P3。

## 9. 缺陷与遗留

| 编号 | 等级 | 问题 | 影响 | 状态/计划 |
| --- | --- | --- | --- | --- |
| `NAV-001` | P3 | 外部租户首页仍请求 `/api/insight/config` 并收到 403 | Network 噪音；页面和导航正常，无权限放宽 | 后续由首页数据请求治理统一处理 |
| `BUILD-001` | P3 | 生产 JS bundle 约 1.46 MB，构建提示超过 500 kB | 不影响本次功能正确性 | 后续统一拆包 |
| `TECH-001` | P3 | 后端测试输出 FastAPI/httpx、PyMySQL、Pydantic 弃用提示 | 不影响验收路径 | 依赖升级时处理 |

- P0/P1：`0/0`
- P2/P3：`0/3`

## 10. 证据索引

- 菜单结构：`frontend/src/app/menu-config.ts`、`frontend/src/app/menu-config.test.ts`
- 侧栏过滤与选中：`frontend/src/components/layout/sidebar-menu.ts`、`sidebar-menu.test.ts`
- 侧栏呈现：`frontend/src/components/layout/sidebar.tsx`
- 路由兼容：`frontend/src/app/navigation-contract.ts`、`router.tsx`、`router-contract.test.ts`
- 上传 HTTP/实库：`backend/tests/test_material_uploads_http.py`、`test_material_uploads_mysql.py`
- 分析 HTTP/聚合：`backend/tests/test_asset_analysis_http.py`、`test_asset_analysis.py`
- 最终架构与迁移：`docs/navigation-architecture.md`、`docs/navigation-migration-map.md`

## 11. 最终结论

```text
当前等级：L3
允许描述：开发完成
未达到 L4 的原因：未部署到授权沙箱/测试环境，也未连接真实外部依赖完成端到端验收
P0/P1：0/0
P2/P3：0/3
下一步：由集成负责人评审两个本地提交；如需提升 L4，另行授权测试环境部署和外部依赖验收
```

外部影响：无 push、无 merge、无 deploy、无生产数据库、无真实平台写入。

