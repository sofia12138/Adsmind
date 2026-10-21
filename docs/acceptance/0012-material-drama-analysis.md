# 功能验收记录：素材与剧目分析

> 本记录遵守 [`../acceptance-standard.md`](../acceptance-standard.md)。未填写或未验证的项目按“不通过/未完成”处理。

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 功能编号 | `0012` |
| 功能名称 | `素材与剧目分析` |
| 分支 | `codex/adsmind-12-material-drama-analysis` |
| Commit SHA | `a13d249`（功能实现）；`d5c17fe`（真实验收测试与验收发现修复）；`d75f5e8`（统一验收基线） |
| 验收日期 | `2026-10-21` |
| 验收环境 | 独立 MySQL `127.0.0.1:3311`；后端 `127.0.0.1:8011`；前端 `127.0.0.1:4011`；临时 datadir `/private/tmp/adsmind-upload-mysql.Eg8ndy` |
| 验收角色 | owner、viewer、同租户无应用成员身份、跨租户 owner |
| 当前等级 | `L3` |
| 允许描述 | `真实集成验收通过（未部署）` |

## 1. 范围与边界

- `GET /api/asset-analysis/report` 支持素材/剧目维度、日期、平台、账户、覆盖状态、搜索和服务端分页。
- APP 读取剧目、素材、有效版本、应用引用、创意组、草稿/快照和平台映射；BIZ 只读取当前应用拥有账户的 `biz_attribution_ad_daily`。
- 仅按 `platform + account_id + platform_asset_id` 与 `video_id/creative_id` 精确归集；缺失、延迟、未映射、未上传、缺版本、无平台数据和部分覆盖不解释为 0。
- 本功能无写 API、无平台调用、无新迁移；迁移链保持 `0001`–`0010`，未占用上传线的 `0011`。
- 未连接生产或共享开发数据库，未使用 `3306/3307`，未调用共享 `8000/4001`，未推送、合并或部署，也未修改菜单信息架构。

### 基线状态

- 统一验收基线：`d75f5e8`（内容等同 `cabd136`）。
- 功能实现：`a13d249`；L2 初始记录：`5d888de`；L3 补充与实库修复：`d5c17fe`。
- 真实库验收发现 `app_creative_groups` 没有 `status` 列，原查询会返回 500；已按真实 `0007` 结构将展示状态投影为兼容值 `active`，未改表、未新增写路径。

## 2. 独立环境与迁移

| 检查项 | 实际结果 | 结果 |
| --- | --- | --- |
| 隔离实例 | `@@port=3311`，socket/datadir 均在 `/private/tmp/adsmind-upload-mysql.Eg8ndy` | 通过 |
| 空库重建 | 只在该实例删除并重建 `adpilot_app`、`adpilot_biz` | 通过 |
| 全新升级 | 当前分支依次应用 `0001`–`0010`，APP/BIZ 初始化完成 | 通过 |
| 再次升级 | 返回 `{"applied": []}` | 通过 |
| 迁移头 | 实库历史精确为 `0001_legacy_baseline` 至 `0010_automation_rules` | 通过 |
| 回滚 | 本功能无新增迁移，按验收标准不为本功能回滚既有迁移 | 不适用 |

验收数据包含两个租户、同租户两个应用、owner/viewer/无应用成员用户、52 个素材和一个剧目，以及完整、延迟、部分、未映射、未上传、缺版本、无平台数据七类覆盖状态。全部数据仅存在于上述临时实例。

## 3. 真实 HTTP 验收

执行：`ADSMIND_HTTP_BASE_URL=http://127.0.0.1:8011 python -m unittest tests.test_asset_analysis_http -v`，结果 `2 passed`。

| 场景 | 实际结果 | 结果 |
| --- | --- | --- |
| 正常 owner GET | 200；`asset_analysis.v1`、`read_only=true`、tenant/application scope 正确；52 条，第一页 50、第二页 2 | 通过 |
| viewer GET | 200；搜索、素材维度和剧目维度均可读 | 通过 |
| 未登录 | 401 | 通过 |
| 缺少/非法参数 | 缺日期、`page=0`、反向日期均 422 | 通过 |
| 同租户无应用成员 | 403 | 通过 |
| 同租户跨应用 | 200 且 `total=0`，scope 为另一应用，不泄漏原应用 52 条 | 通过 |
| 跨租户 | 200 且 `total=0`，不泄漏原租户数据 | 通过 |
| 状态与口径 | 七类状态均出现；完整素材 spend=10、revenue=20、ROI=2；不完整对象 ROI/缺失指标保持 `null` | 通过 |
| 剧目汇总 | 一个剧目、52 个素材、覆盖 `partial`、ROI 留空 | 通过 |
| 重复 GET | 两次响应完全一致 | 通过 |
| 依赖失败 | 临时移走隔离 BIZ 事实表后返回 500；恢复表后重新 200/52 条 | 通过 |
| 零写入 | 请求前后素材、映射、事实表 count/SUM(id) 与 `app_oplog` 指纹完全一致 | 通过 |

额外只读回读：分析相关 `app_oplog` 数量为 `0`。依赖故障测试只在隔离库临时重命名表并在 `finally` 中恢复，不涉及业务记录或外部系统。

## 4. 浏览器点击验收

浏览器经 `4011` Vite 代理实际访问 `8011`；先退出清理旧 localStorage 应用上下文，再分别登录真实角色。

| 角色/状态 | 操作与可见结果 | Network / Console | 结果 |
| --- | --- | --- | --- |
| owner | “数据分析 → 素材与剧目分析”菜单可见；首页显示 52 对象、3/5 映射、3/4 日报；ROI 2.00 | 实际 GET 200；Console 无 error | 通过 |
| viewer | 真实账号登录，菜单可见，页面显示 52 条与 1/2 页 | 实际 GET 200；Console 无 error | 通过 |
| 无应用成员 | 真实账号登录后直接访问 `/asset-analysis`，页面显示“当前用户无权访问此应用” | API 403 | 通过 |
| 分页 | 点击下一页显示“第 2/2 页”，表格 2 行 | GET `page=2` 200 | 通过 |
| 搜索 | 搜索 `Acceptance material 01` 后仅 1 条 | GET 200 | 通过 |
| 平台/账户/覆盖筛选 | `tiktok` + 验收账户 + `complete` 返回筛选后的 2 条；第二映射被账户筛掉后素材 07 在该筛选内成为完整 | GET 200 | 通过 |
| 维度切换 | 切到剧目汇总显示 1 项、52 个素材、1 个完整、整体部分覆盖、ROI `—` | GET `dimension=drama` 200 | 通过 |
| 详情抽屉 | 点击素材 01 显示 10/20 USD、ROI 2、截止时间、1/1 映射、USD/Asia/Shanghai 和完整链路 | 无写请求 | 通过 |
| 空态 | 不存在的搜索词显示“没有记录；这不代表指标为 0” | GET 200/空列表 | 通过 |
| 错误态 | 临时中断隔离 BIZ 依赖后页面显示“服务器内部错误” | GET 500 | 通过 |
| 恢复/刷新 | 恢复事实表并刷新，回到 52 条、第 1/2 页 | GET 200 | 通过 |

Console 核对没有 error。记录到两类非阻断 warning：React Router v7 future flag，以及无头浏览器中 Recharts 初始容器尺寸 `-1`。Vite/backend access log 同时证明正常 200、权限 403、故障 500 与恢复 200 的请求链。

## 5. 自动化检查

| 检查 | 结果 |
| --- | --- |
| 后端完整回归（启用隔离 MySQL/集成测试） | `129 passed, 2 skipped`；两项 skip 是需运行服务的 HTTP 套件，已另行 `2 passed` |
| 前端完整测试 | `5 files / 40 tests passed` |
| 生产构建 | 通过；仅保留既有 bundle >500 kB warning |
| 修改文件 ESLint | 通过：分析页、服务、服务测试、Vite 配置 |
| 差异检查 | `git diff --check` 通过 |
| 完整仓库 ESLint | 基线仍为 20 error / 3 warning；均不在本功能文件，未混入无关修复 |

## 6. 缺陷与遗留

| 编号 | 等级 | 问题 | 影响 | 处理 |
| --- | --- | --- | --- | --- |
| FIX-001 | P1（已关闭） | 实库创意组查询引用不存在的 `g.status` | 正常报表 500 | `d5c17fe` 修复并通过实库 HTTP/浏览器复验 |
| BASE-001 | P2 | 全仓 ESLint 基线 20 error / 3 warning | 不影响本功能专项 lint、测试和构建 | 由基线专项处理 |
| UI-001 | P2 | 无头浏览器记录 Recharts 初始尺寸 warning | 数据与交互正常，Console 无 error | 后续可给图表容器增加显式最小尺寸 |
| UI-002 | P3 | React Router v7 future flag warning | 仅升级提示 | 随路由升级统一处理 |
| BUILD-001 | P3 | 构建 bundle 大于 500 kB | 不影响本功能正确性 | 后续统一拆包 |

- 未关闭 P0/P1：`0/0`
- 未关闭 P2/P3：`2/2`

## 7. 证据索引

- 真实 HTTP 自动化：`backend/tests/test_asset_analysis_http.py`。
- API/聚合实现：`backend/asset_analysis/routes.py`、`service.py`、`repository.py`。
- 浏览器实现：`frontend/src/pages/AssetAnalysisPage.tsx`、`frontend/src/services/asset-analysis.ts`。
- 独立代理配置：`frontend/vite.config.ts`，通过 `VITE_API_PROXY_TARGET=http://127.0.0.1:8011` 指向隔离后端，默认行为仍为 `8000`。
- 口径：`docs/asset-analysis.md`。
- 命令输出与浏览器 DOM/Console 证据保存在本次 Codex Session；未截取或保存任何生产数据。

## 8. 最终结论

```text
当前等级：L3
允许描述：真实集成验收通过（未部署）
P0/P1：0/0
P2/P3：2/2
外部影响：无生产数据库、无真实平台写、无发布、无部署
发布状态：仅本地分支验收完成，尚未推送/合并/部署
```

验收人：`Codex Session 0012`  
验收日期：`2026-10-21`
