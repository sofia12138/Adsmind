# AdsMind 导航迁移映射

> 状态：已实施  
> 基线：`b7f0257f93fa07a342e9abad960c4a1b1d79a293`  
> 原则：只移动或隐藏导航，保留页面、路由、权限与服务端鉴权。

## 1. 移动入口

| 入口 | 原路径 | 原分组 | 最终分组 | 保留约束 |
| --- | --- | --- | --- | --- |
| 账户组 | `/settings/account-groups` | 系统管理 | 广告资产库 | `account_groups`、应用隔离、原 URL 不变 |
| 命名规则 | `/settings/naming-rules` | 系统管理 | 广告资产库 | `naming_rules`、应用隔离、原 URL 不变 |

两个入口在最终导航中各出现一次，不在“系统管理”重复显示。

## 2. 确认隐藏入口

| 入口 | 原路径 | 权限键 | 导航结果 | 直接访问结果 |
| --- | --- | --- | --- | --- |
| 广告草稿 | `/ads/drafts` | `ad_create` | 隐藏 | 路由保留，继续鉴权 |
| 平台执行预检 | `/ads/platform-preflight` | `platform_preflight` | 隐藏 | 路由保留，继续鉴权 |
| 模板管理 | `/templates` | `template_mgmt` | 隐藏 | 路由保留，继续鉴权 |
| TikTok 素材上传 | `/tiktok-materials` | `tiktok_materials` | 隐藏 | 路由保留，继续鉴权 |

## 3. 统一基线后的临时入口收敛

`b7f0257` 已包含后集成的“素材与剧目分析”临时菜单入口。确认的 49 节点没有该入口，且原组合验收记录要求其随统一信息架构收敛。因此本次从菜单配置移除该临时入口，但保留：

- 页面和原路由 `/asset-analysis`；
- `creatives` 前端权限；
- `/api/asset-analysis/report` 服务端权限、租户/应用隔离和只读语义；
- 直接访问、真实 HTTP 和浏览器关键回归。

这不是删除“素材与剧目分析”功能，也不把它合并到“素材分析”页面。

## 4. 保持不变的兼容项

- 所有最终可见节点沿用原 `path`、`panelKey`、`pluginKey`、`internalOnly` 和 `externalUrl`。
- `/ads/create-tiktok-minis?...` 继续把完整查询参数透传到 `/ads/create?...`。
- 被隐藏入口的页面组件、路由和接口均未删除。
- 本次没有后端业务代码、数据库模型或迁移变更。

## 5. 验证映射

| 风险 | 自动化/验收覆盖 |
| --- | --- |
| 节点数量或顺序漂移 | `menu-config.test.ts` 固定 10 个根节点、49 个总节点及关键子项顺序 |
| 移动入口重复 | 断言“账户组”“命名规则”各出现一次且只属于广告资产库 |
| 隐藏导致路由删除 | `navigation-contract.ts` 与 `router-contract.test.ts` 统一保留路由和权限键 |
| `/ads/create` 双高亮 | `sidebar-menu.test.ts` 验证唯一叶子选中；真实浏览器复验 |
| 角色/插件/internalOnly 漂移 | `filterMenu` 专项测试 + 多角色真实浏览器验收 |
| 横向滚动和点击死区 | 319px 与 2091px 真实浏览器尺寸检查 `scrollWidth === clientWidth` |
| 素材功能回归 | 素材上传、素材/剧目分析真实 HTTP 专项和浏览器直达回归 |

