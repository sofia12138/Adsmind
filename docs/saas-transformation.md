# AdsMind 通用广告 SaaS 改造方案

> 状态：草案 v1.0 · 待评审
> 作者：研发
> 日期：2026-05-13
> 关联：`README.md` · `docs/project-structure.md` · `docs/deployment.md`

> 注意：本文保留早期方案和阶段记录。租户/应用鉴权、数据作用域、后台任务、缓存、文件与
> 显式迁移的当前强制约定以 [租户与应用隔离契约](tenant-application-contract.md) 为准；
> 本文中未验签 Header、中间件默认 internal tenant、启动时自动 DDL/回填等旧方案均已废止。

---

## 0. 文档目的

本方案描述把现有的内部投放系统 **AdsMind**（短剧出海业务）改造为**通用广告 SaaS** 的工程路径、关键决策、分阶段路线图与风险登记。本文档同时作为评审依据与后续 PR 拆解的索引。

---

## 1. 执行摘要（TL;DR）

- **目标**：在不破坏现有内部业务的前提下，把 AdsMind 升级为可对外服务的多租户广告 SaaS。
- **路径**：A → B 渐进。**A 档位**（行业版 / 短剧出海多客户入驻）作为 9 周内可上线的 MVP；**B 档位**（通用投放 SaaS）在 A 之上再花约 11 周达成。
- **隔离策略**：共享数据库 + 行级 `tenant_id`（最轻量，匹配现有单 MySQL 多库架构）。
- **平台扩展**：现有 TikTok / Meta 之外，新增 **Google Ads**、**巨量引擎**、**Snapchat**。
- **商业化**：Hybrid（自助订阅 Stripe + 销售人工开通），AI 能力作为付费 add-on。
- **数据隔离原则**：内部租户 `tenant_id=1` 默认启用全部插件（drama、optimizer、metis 归因、ops_panel）；外部租户默认仅启用通用核心。

里程碑：

| 时间 | 状态 | 内容 |
|---|---|---|
| W9 末 | A 档位 MVP 上线 | 多租户骨架 + OAuth + 业务插件化 |
| W14 末 | 平台扩展完成 | Google / 巨量 / Snapchat 适配器 |
| W20 末 | B 档位 MVP 上线 | 计费 + 自助注册 + API Key |

---

## 2. 现状评估

### 2.1 技术栈

| 层 | 技术 | 备注 |
|---|---|---|
| 后端 | FastAPI · PyMySQL · APScheduler · loguru | 单进程，调度内嵌 |
| 前端 | React 19 · Vite · TypeScript · TanStack Query · Tailwind v4 | 面板权限模型 `panelKey` |
| 数据库 | MySQL 8.0（4 库：PRD/APP/BIZ/ORDER） | PRD 只读，ORDER = PolarDB |
| 数仓 | 阿里云 MaxCompute · ClickHouse（via DMS Enterprise OpenAPI） | 强依赖内网 |
| 平台 | TikTok Marketing API · Meta Marketing API | `integrations/base.py` 薄抽象 |
| 认证 | JWT + bcrypt | 单租户 RBAC |

### 2.2 业务耦合点（短剧出海专有，不可作为 SaaS 核心）

- `drama_*` / `fact_drama_daily` / `ad_drama_mapping`
- `optimizer_*` / `fact_optimizer_daily` / `campaign_optimizer_mapping`
- `biz_attribution_ad_daily` / `_intraday`（依赖 MaxCompute + DMS）
- `ad_returned_conversion_daily`（依赖归因数仓）
- `biz_ops_daily*`（依赖 PolarDB `matrix_order`）
- `_probe_*.py` 一系列探针脚本（数据对账专用）

### 2.3 缺失能力

| 缺口 | 影响 |
|---|---|
| 无 `tenant_id` 字段 | 完全单租户，无法对外服务 |
| 凭证明文存储 | 合规风险高 |
| 无 OAuth 流程 | 客户接入门槛极高 |
| 适配器接口残缺 | 只能 list/update_status，无法 create/insights/upload |
| APScheduler 单点 | 多租户后调度无法隔离 |
| 无计费 / 套餐 / 配额 | 无法商业化 |
| 无审计与限流 | 滥用风险与平台 API 风控风险 |

---

## 3. 目标 SaaS 形态

### 3.1 渐进路线（已决策：AB 渐进）

```
[现状: 内部单租户]
        │
        ▼
[A 档位: 行业版 SaaS]      W1 ─ W9
        │ - 多租户骨架
        │ - 凭证安全 + OAuth
        │ - 业务模块插件化
        │ - 内部租户 = 全功能；外部租户 = 通用核心
        ▼
[B 档位: 通用投放 SaaS]    W10 ─ W20
        │ - 平台适配器全量补齐（Google/巨量/Snapchat）
        │ - 任务调度租户化 + 配额限流
        │ - Hybrid 计费 + 自助注册 + API Key
        ▼
[C 档位: PLG / 白标]        W21+ （可选）
          - AI add-on 商业化、白标、SSO、Webhooks
```

### 3.2 客户画像

| 档位 | 目标客户 | ARPU 区间 | 接入方式 |
|---|---|---|---|
| A | 同行业短剧 / 小说 / 出海 App 厂商 5~50 家 | 中~高 | 销售对接 + OAuth |
| B | 任意出海广告主、电商品牌 | 中 | 自助注册 + OAuth |
| C | 中小广告主长尾、机构客户 | 低~中 | 自助 + 白标 |

---

## 4. 关键设计决策（已拍板）

| 决策项 | 选择 | 理由 |
|---|---|---|
| SaaS 形态 | **AB 渐进** | 先把短剧行业打透，再扩通用 |
| 隔离策略 | **共享 DB + 行级 `tenant_id`** | 与现有 MySQL 架构一致，迁移成本最低 |
| 新增平台 | **Google Ads / 巨量引擎 / Snapchat** | 出海三大 + 国内必备 |
| 计费形态 | **Hybrid（Stripe 自助 + 销售人工）** | 兼顾长尾与大客户 |
| AI 策略 | **AI 作付费 add-on** | 先稳投放管理，再做差异化 |
| 内部业务 | **作为插件保留，仅内部租户启用** | 不破坏现有交付 |

---

## 5. 总体架构（目标态）

```
                          ┌────────────────────┐
                          │   Web (React SPA)  │
                          └──────────┬─────────┘
                                     │ /api/* + X-Tenant-Id
                          ┌──────────▼─────────┐
                          │  Nginx / API GW    │  租户路由、限流
                          └──────────┬─────────┘
                                     │
        ┌────────────────────────────┼───────────────────────────┐
        │                            │                           │
┌───────▼────────┐         ┌─────────▼────────┐         ┌────────▼────────┐
│ FastAPI Core   │         │ FastAPI Plugins  │         │ Billing/Quota   │
│ - auth         │         │ - drama          │         │ - Stripe        │
│ - tenants      │         │ - optimizer      │         │ - usage counter │
│ - accounts     │         │ - attribution    │         └─────────────────┘
│ - campaigns    │         │ - ops_panel      │
│ - insights     │         │ - ai_studio      │
└───────┬────────┘         └────────┬─────────┘
        │                           │
        └──────────┬────────────────┘
                   │
   ┌───────────────┼──────────────────────────────────────┐
   │               │                                      │
┌──▼──────┐ ┌──────▼──────┐ ┌────────────┐ ┌─────────────▼─────┐
│ APP DB  │ │  BIZ DB     │ │ PRD/ORDER  │ │  External APIs    │
│ 元数据   │ │ 广告业务数据 │ │ 内网数据源  │ │  TikTok/Meta/Google│
│ 租户/计费│ │ + tenant_id │ │ (仅插件)    │ │  /巨量/Snapchat   │
└─────────┘ └─────────────┘ └────────────┘ └───────────────────┘
                   │
            ┌──────▼──────┐
            │ APScheduler │   阶段5 视情况升级 Celery
            │ + per-tenant│
            └─────────────┘
```

---

## 6. 数据模型改造

### 6.1 新增表（APP 库）

```sql
-- 租户
CREATE TABLE app_tenants (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  slug            VARCHAR(64)  NOT NULL UNIQUE,
  name            VARCHAR(200) NOT NULL,
  plan_id         VARCHAR(50)  NOT NULL DEFAULT 'free',
  status          VARCHAR(20)  NOT NULL DEFAULT 'active',
  is_internal     TINYINT      NOT NULL DEFAULT 0,
  enabled_plugins JSON         DEFAULT NULL,
  settings        JSON         DEFAULT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 租户成员（替代 assigned_accounts 的语义）
CREATE TABLE app_tenant_members (
  tenant_id  BIGINT NOT NULL,
  user_id    BIGINT NOT NULL,
  role       VARCHAR(50) NOT NULL DEFAULT 'member',
  joined_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tenant_id, user_id),
  INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 套餐
CREATE TABLE app_plans (
  id                  VARCHAR(50) PRIMARY KEY,
  name                VARCHAR(100) NOT NULL,
  accounts_limit      INT  NOT NULL DEFAULT 1,
  api_calls_monthly   INT  NOT NULL DEFAULT 10000,
  ai_calls_monthly    INT  NOT NULL DEFAULT 0,
  sync_interval_min   INT  NOT NULL DEFAULT 60,
  data_retention_days INT  NOT NULL DEFAULT 30,
  price_monthly_cents INT  NOT NULL DEFAULT 0,
  features            JSON DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 订阅
CREATE TABLE app_subscriptions (
  tenant_id    BIGINT PRIMARY KEY,
  plan_id      VARCHAR(50) NOT NULL,
  period_start DATETIME NOT NULL,
  period_end   DATETIME NOT NULL,
  status       VARCHAR(20) NOT NULL DEFAULT 'active',
  external_ref VARCHAR(200) DEFAULT NULL,
  source       VARCHAR(20) NOT NULL DEFAULT 'self',
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用量
CREATE TABLE app_usage_counters (
  tenant_id BIGINT NOT NULL,
  metric    VARCHAR(50) NOT NULL,
  period_ym CHAR(7) NOT NULL,
  value     BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, metric, period_ym)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- API Key（对外开放）
CREATE TABLE app_api_keys (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  tenant_id   BIGINT NOT NULL,
  name        VARCHAR(100) NOT NULL,
  key_prefix  VARCHAR(16) NOT NULL,
  key_hash    VARCHAR(255) NOT NULL,
  scopes      JSON DEFAULT NULL,
  last_used_at DATETIME DEFAULT NULL,
  revoked_at  DATETIME DEFAULT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_tenant (tenant_id),
  UNIQUE KEY uk_prefix (key_prefix)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 调度任务（租户化）
CREATE TABLE app_scheduled_jobs (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  tenant_id   BIGINT NOT NULL,
  job_type    VARCHAR(50) NOT NULL,
  config      JSON NOT NULL,
  cron        VARCHAR(50) NOT NULL,
  enabled     TINYINT NOT NULL DEFAULT 1,
  last_run_at DATETIME DEFAULT NULL,
  next_run_at DATETIME DEFAULT NULL,
  INDEX idx_next_run (enabled, next_run_at),
  INDEX idx_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- OAuth 凭证（替代明文 access_token）
CREATE TABLE app_oauth_credentials (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  tenant_id       BIGINT NOT NULL,
  platform        VARCHAR(20) NOT NULL,
  external_id     VARCHAR(100) NOT NULL,
  access_token_enc LONGBLOB NOT NULL,
  refresh_token_enc LONGBLOB DEFAULT NULL,
  expires_at      DATETIME DEFAULT NULL,
  scopes          JSON DEFAULT NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_platform_external (tenant_id, platform, external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.2 现有表改造清单

| 库 | 表 | 改造 |
|---|---|---|
| APP | `app_users` | + `tenant_id`（主属租户） |
| APP | `app_templates` / `app_oplog` / `app_insight_config` | + `tenant_id` |
| APP | `asset_landing_pages` / `asset_copy_packs` / `asset_region_groups` | + `tenant_id` |
| APP | `panel_definitions` | + `is_plugin VARCHAR(50) NULL`（标记所属插件） |
| APP | `role_panel_permissions` / `user_panel_permissions` | + `tenant_id` |
| BIZ | `biz_ad_accounts` | + `tenant_id`，UNIQUE → `(tenant_id, platform, account_id)` |
| BIZ | `biz_campaigns` / `biz_adgroups` / `biz_ads` | + `tenant_id` |
| BIZ | `biz_campaign/adgroup/ad_daily_normalized` | + `tenant_id` + 索引前缀 |
| BIZ | `biz_attribution_ad_daily` / `_intraday` | + `tenant_id`（**仅插件写入**） |
| BIZ | `ad_returned_conversion_daily` | + `tenant_id` |
| BIZ | `biz_ops_daily*` | + `tenant_id`（**仅插件写入**） |
| BIZ | `ad_drama_mapping` / `fact_drama_daily` | + `tenant_id`（**仅插件写入**） |
| BIZ | `campaign_optimizer_mapping` / `fact_optimizer_daily` / `optimizer_*` | + `tenant_id`（**仅插件写入**） |
| BIZ | `biz_sync_logs` / `tiktok_material_uploads` | + `tenant_id` |

### 6.3 迁移策略

- 一次性 ALTER：所有表 `ADD COLUMN tenant_id BIGINT NOT NULL DEFAULT 1`
- 兜底数据：`INSERT INTO app_tenants (id=1, slug='internal', name='AdsMind 内部', is_internal=1)`
- UNIQUE 重建：先 `DROP KEY ...` 再 `ADD UNIQUE KEY uk_xxx (tenant_id, ...)`
- 由 `backend/scripts/migrate/001_add_tenant_id.py` 完成，**幂等可重跑**
- staging 演练 → 生产维护窗口执行

---

## 7. 后端改造

### 7.1 目录结构（目标态）

```
backend/
├─ app.py                    # FastAPI 入口（plugin loader 接入）
├─ config.py                 # 增加 SaaS 相关配置
├─ db.py                     # 现有三库 + 加密工具
├─ auth.py                   # JWT + tenant_id claim
├─ core/                     # 🆕 通用基础设施
│  ├─ tenant.py              # 租户上下文（Depends + middleware）
│  ├─ plugin_loader.py       # 插件注册与加载
│  ├─ quota.py               # 配额装饰器
│  ├─ rate_limit.py          # 租户级限流
│  └─ crypto.py              # AES-GCM 凭证加解密
├─ routes/                   # 通用核心路由（已存在大量，逐步剥离）
├─ services/                 # 业务逻辑层
├─ repositories/             # 数据访问层（全部接收 tenant_id）
├─ integrations/             # 平台适配器
│  ├─ base.py                # 重写为完整接口
│  ├─ registry.py
│  ├─ oauth_base.py
│  ├─ meta/      adapter.py oauth.py
│  ├─ tiktok/    adapter.py oauth.py
│  ├─ google/    adapter.py oauth.py      🆕
│  ├─ oceanengine/ adapter.py oauth.py    🆕
│  └─ snapchat/  adapter.py oauth.py      🆕
├─ plugins/                  # 🆕 业务插件（短剧业务专属）
│  ├─ drama/
│  ├─ optimizer/
│  ├─ attribution_metis/
│  ├─ returned_conversion/
│  ├─ ops_panel_polardb/
│  └─ ai_studio/             # AI add-on
├─ billing/                  # 🆕 计费
│  ├─ stripe_client.py
│  ├─ manual_billing.py
│  └─ webhook.py
└─ scripts/
   └─ migrate/               # 🆕 schema 迁移
      ├─ 001_add_tenant_id.py
      ├─ 002_encrypt_credentials.py
      └─ 003_seed_plans.py
```

### 7.2 租户上下文

```python
# backend/core/tenant.py
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request

@dataclass
class TenantCtx:
    id: int
    slug: str
    plan_id: str
    enabled_plugins: list[str]
    is_internal: bool

def get_current_tenant(request: Request) -> TenantCtx:
    # 优先级：API Key > JWT.tenant_id > X-Tenant-Id Header
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(401, "未识别租户")
    return tenant
```

中间件 `TenantMiddleware` 负责按上述优先级填充 `request.state.tenant`，并校验 `tenant.status='active'`。

### 7.3 Repository 改造原则

**显式参数优先，避免魔法注入**：

```python
# 改造前
def list_by_platform(platform: str) -> list[dict]:
    cur.execute("SELECT * FROM biz_ad_accounts WHERE platform=%s", (platform,))

# 改造后
def list_by_platform(tenant_id: int, platform: str) -> list[dict]:
    cur.execute(
        "SELECT * FROM biz_ad_accounts WHERE tenant_id=%s AND platform=%s",
        (tenant_id, platform),
    )
```

- 所有 repository 方法第一个参数强制 `tenant_id: int`
- CI 加 lint：扫描 SQL 语句若涉及多租户表却未出现 `tenant_id =` → 失败
- Service 层 `accept tenant_id` 并往下透传
- Route 层从 `Depends(get_current_tenant)` 取值

### 7.4 插件加载

```python
# backend/core/plugin_loader.py
class Plugin:
    name: str
    panels: list[str]
    requires_env: list[str] = []
    def register_routes(self, app): ...
    def register_jobs(self, scheduler): ...
    def is_available(self, settings) -> bool:
        return all(getattr(settings, k, None) for k in self.requires_env)

REGISTRY: dict[str, Plugin] = {}

def register(plugin: Plugin):
    REGISTRY[plugin.name] = plugin

def load_all(app, scheduler, settings, internal_tenant_id: int = 1):
    for name, p in REGISTRY.items():
        if not p.is_available(settings):
            logger.info(f"插件 {name} 缺少依赖，跳过加载")
            continue
        p.register_routes(app)
        p.register_jobs(scheduler)
```

每个插件 `plugins/<name>/__init__.py` 注册一个 `Plugin` 实例。Route 内部仍然要走 `tenant.enabled_plugins` 二次校验（防止其它租户访问未启用的插件）。

### 7.5 凭证加密

- 算法：AES-256-GCM（key 32 字节，nonce 12 字节，tag 16 字节）
- 主密钥来源：
  - 开发：环境变量 `ENCRYPTION_KEY_B64`
  - 生产：AWS KMS / 阿里 KMS / HashiCorp Vault（按部署环境）
- 存储格式：`nonce(12) || ciphertext || tag(16)`，整体 base64 后入库（`LONGBLOB`）
- 工具：`backend/core/crypto.py` 提供 `encrypt(plain: str) -> bytes` / `decrypt(blob: bytes) -> str`
- 迁移脚本 `002_encrypt_credentials.py`：把现有 `biz_ad_accounts.access_token` 明文 → `app_oauth_credentials.access_token_enc`，旧字段保留两周后删除

### 7.6 OAuth 流程

```
POST /api/integrations/{platform}/oauth/start
  → 返回授权 URL + state（state 绑定 tenant_id, csrf）

GET  /api/integrations/{platform}/oauth/callback
  → 校验 state → exchange code → 拉取账户列表 → 写 app_oauth_credentials + biz_ad_accounts

POST /api/integrations/{platform}/oauth/refresh   # 后台 job 调用
```

### 7.7 配额与限流

```python
# backend/core/quota.py
@consume_quota("api_calls", n=1)
async def some_route(...): ...

@consume_quota("ai_calls", n=1)
async def ai_generate(...): ...
```

实现：
- Redis 优先（O(1)），降级到 `app_usage_counters` 表
- 月初重置，超额返回 `429 Quota Exceeded`
- 平台 API 调用按 `tenant_id` 二级限流（防单租户拖垮全局），库：`slowapi` + Redis

---

## 8. 前端改造

### 8.1 关键变更

| 模块 | 变更 |
|---|---|
| `contexts/AuthContext.tsx` | 增加 `tenantId`、`tenantSlug`、`plan`、`enabledPlugins` 状态 |
| 请求层 | 所有 `/api/*` 自动注入 `X-Tenant-Id` 头（多 tenant 切换） |
| `app/menu-config.ts` | 按 `enabledPlugins` 过滤短剧/优化师/归因/运营面板等菜单项 |
| 新增 `/onboarding` | 注册 → 创建 tenant → 邀请成员 → OAuth 接平台 |
| 新增 `/settings/billing` | 套餐展示 / 升降级 / 用量看板 |
| 新增 `/settings/team` | 成员管理 / 邀请 |
| 新增 `/settings/integrations` | 一键 OAuth 接 TikTok/Meta/Google/巨量/Snapchat |
| 新增 `/settings/api-keys` | API Key 管理 |
| 顶部租户切换器 | 一个用户多 tenant 场景 |

### 8.2 菜单插件化示例

```ts
const isPluginEnabled = (key: string) =>
  auth.enabledPlugins?.includes(key) ?? auth.role === 'super_admin'

const filtered = menuConfig.filter(item => {
  if (item.id === 'drama-analysis')          return isPluginEnabled('drama')
  if (item.id === 'optimizer-performance')   return isPluginEnabled('optimizer')
  if (item.id === 'returned-conversion')     return isPluginEnabled('returned_conversion')
  if (item.id === 'ops-dashboard')           return isPluginEnabled('ops_panel_polardb')
  return true
})
```

---

## 9. 平台适配器扩展

### 9.1 完整接口

```python
# backend/integrations/base.py
class AdsPlatformAdapter(ABC):
    platform: str
    # — 结构层
    async def list_accounts(self) -> list[AccountDTO]: ...
    async def list_campaigns(self, account_id, **f) -> list[CampaignDTO]: ...
    async def list_adgroups(self, ...): ...
    async def list_ads(self, ...): ...
    # — 写入
    async def create_campaign(self, dto): ...
    async def update_campaign(self, id, patch): ...
    async def pause(self, ids): ...
    async def resume(self, ids): ...
    async def update_budget(self, id, amount): ...
    # — 报表
    async def fetch_insights(self, level, account_id, date_range, breakdowns): ...
    # — 素材
    async def upload_video(self, account_id, file_or_url) -> MediaDTO: ...
    async def upload_image(self, account_id, file_or_url) -> MediaDTO: ...
    # — OAuth
    async def exchange_code(self, code) -> TokenBundle: ...
    async def refresh_token(self, refresh_token) -> TokenBundle: ...
```

### 9.2 优先级与工期

| 适配器 | 优先级 | 估时 | 说明 |
|---|---|---|---|
| TikTok 重构 | P0 | 0.5 周 | 现有逻辑迁到新接口 |
| Meta 重构 | P0 | 0.5 周 | 同上 |
| Google Ads | P1 | 2 周 | gRPC、Customer ID/Resource Name 概念 |
| 巨量引擎 | P1 | 1.5 周 | 国内市场必备，REST API |
| Snapchat | P2 | 1 周 | 实现量最小 |

---

## 10. 调度与任务

### 10.1 阶段 1~3：APScheduler 租户化（不引入新基础设施）

- 现有 8 个 job 全部改造为接收 `tenant_id` 参数
- `sync_all_job` 改为：

```python
async def _sync_all_job():
    for tenant in tenant_repository.list_active():
        if not tenant.enabled_plugins or "core_ads" not in tenant.enabled_plugins:
            continue
        try:
            await sync_run(tenant_id=tenant.id, ...)
        except Exception as e:
            logger.error(f"tenant={tenant.id} 同步失败: {e}")
```

- 内部租户专用任务（`sync_drama` / `sync_optimizer` / `sync_attribution_*` / `sync_ops_*`）：判断 `if tenant.is_internal:` 才跑

### 10.2 阶段 5：升级 Celery（条件触发）

触发条件之一即升级：
- 活跃租户数 > 20
- 单租户同步耗时 > 5 分钟
- APScheduler 单点风险变现

升级内容：
- Celery + Redis broker + Redis result backend
- 队列：`critical` / `default` / `sync_heavy` / `tenant_<id>`（VIP 隔离）
- Flower 监控；失败重试 + 死信队列

---

## 11. 计费方案（Hybrid）

### 11.1 套餐设计（初版）

| Plan | 月价 | 账户数 | API/月 | AI/月 | 同步频率 | 保留天数 |
|---|---|---|---|---|---|---|
| Free | $0 | 1 | 5,000 | 0 | 60 min | 30 |
| Starter | $49 | 3 | 50,000 | 100 | 30 min | 90 |
| Pro | $199 | 10 | 300,000 | 1,000 | 15 min | 180 |
| Business | $499 | 30 | 1,000,000 | 5,000 | 10 min | 365 |
| Enterprise | 谈 | 无限 | 谈 | 谈 | 5 min | 谈 |

数字仅占位，**正式定价需市场对标后再定**。

### 11.2 实现要点

- **自助流**：Stripe Checkout / Billing Portal；Webhook 接收升降级、支付失败、退订
- **销售流**：admin 后台手工创建 `app_subscriptions`，`source='sales'`，跳过 Stripe
- **用量看板**：`/settings/billing` 实时显示当月用量与剩余配额
- **超额策略**：默认硬限（429），企业版可配置软限 + 邮件告警

---

## 12. AI Add-on（`plugins/ai_studio`）

### 12.1 能力

- **文案生成**：复用现有 `services/delivery_language.py`，支持多语言、多变体
- **素材打标**：上传视频/图片 → 自动提取标签（场景/人物/情绪）
- **创意推荐**：基于历史投放数据 + LLM 给出标题/描述建议
- **诊断助手**：基于报表数据 → 自然语言总结 + 优化建议

### 12.2 计费

- 按 `ai_calls` 计量
- 高级模型（GPT-4 / Claude Opus）按 token 二次计量
- 配额耗尽 → 提示升级或单独购买 add-on

---

## 13. 安全与合规

| 维度 | 措施 |
|---|---|
| 凭证 | AES-256-GCM 加密，主密钥外部托管 |
| 传输 | HTTPS 强制；HSTS |
| 认证 | JWT 短期 token + refresh token；密码 bcrypt cost=12 |
| 授权 | 行级 tenant 隔离 + RBAC + panel 权限 |
| 审计 | `app_oplog` 增加 `tenant_id` / `ip` / `user_agent` / `request_id` |
| 限流 | per-tenant rate limit；平台 API 调用降级队列 |
| 数据导出 | 客户可一键导出本租户全部数据（GDPR 友好） |
| 数据删除 | 注销租户后保留 30 天软删除 → 物理删除 |
| 密钥轮换 | 季度轮换；新旧密钥共存窗口 7 天 |
| 平台合规 | Meta/TikTok/Google 三方账户授权范围最小化 |

---

## 14. 监控与运维

| 类型 | 工具 | 关键指标 |
|---|---|---|
| 应用日志 | loguru → Loki / 阿里云 SLS | 错误率、慢请求 |
| 指标 | Prometheus + Grafana | QPS、p95 延迟、同步成功率、配额命中率 |
| 错误追踪 | Sentry | 异常聚合、版本回滚 |
| 平台 API 健康 | 自定义 dashboard | TikTok/Meta/Google 限流命中率、token 失效率 |
| 业务指标 | 自有 BI | 活跃租户、ARR、Churn、AI 调用量 |
| 告警 | 飞书 / Slack | P0 故障、配额超限、同步失败、token 过期 |

---

## 15. 分阶段实施路线图

> 假设：1 名后端 + 1 名前端 + 0.5 PM/QA。

### 阶段 0 — 准备（W1）

- [ ] 评审通过本方案
- [ ] 锁定一期插件清单、套餐定价占位
- [ ] 搭建 staging 环境
- [ ] 写迁移生成器骨架（基于 `db.py` 的 DDL 列表）

**交付物**：评审纪要、staging 链接、`scripts/migrate/_generator.py`

### 阶段 1 — 多租户骨架（W2~W4）

- [ ] 新建 `app_tenants` / `app_tenant_members` / `app_plans` / `app_subscriptions` / `app_usage_counters` / `app_api_keys` / `app_oauth_credentials` / `app_scheduled_jobs`
- [ ] 全业务表 `ADD COLUMN tenant_id` + UNIQUE 重建
- [ ] 数据回填：所有现有行 → `tenant_id=1`；创建 internal tenant
- [ ] `auth.py` JWT 增加 `tenant_id` claim；登录返回租户列表供前端选择
- [ ] `backend/core/tenant.py` + 中间件
- [ ] 所有 repository 改造（第一个参数 `tenant_id`）
- [ ] 前端 AuthContext + 请求 header
- [ ] 顶部租户切换器（先做骨架，只有 1 个内部租户）

**验收**：
- 现有用户登录后行为完全一致
- 数据库所有业务表 100% 覆盖 `tenant_id`
- 单测覆盖 tenant 中间件、Repository 改造
- 灰度上线，回滚预案就绪

**风险**：DDL 量大、UNIQUE 重建可能锁表。**缓解**：维护窗口执行；大表用 `pt-online-schema-change`。

### 阶段 2 — 凭证安全 + OAuth（W5~W6）

- [ ] `core/crypto.py` 实现 + 密钥管理
- [ ] 迁移脚本 `002_encrypt_credentials.py`
- [ ] TikTok / Meta OAuth 授权码流程（start + callback）
- [ ] `app_oauth_credentials` 上线
- [ ] 后台 job：refresh token 临近到期自动续期
- [ ] 前端 `/settings/integrations` 一键授权页面
- [ ] 审计日志加 `tenant_id`

**验收**：明文凭证下线；OAuth 流跑通可演示

### 阶段 3 — 业务插件化（W7~W9，**A 档位 MVP**）

- [ ] `backend/core/plugin_loader.py`
- [ ] 抽取 `drama` / `optimizer` / `attribution_metis` / `returned_conversion` / `ops_panel_polardb` 到 `plugins/`
- [ ] 内部租户默认启用全部插件；其它租户默认不启用
- [ ] `panel_definitions` 增加 `is_plugin` 字段
- [ ] 前端菜单按 `enabledPlugins` 过滤
- [ ] 新建租户引导流程（创建 tenant → 选行业 → 接平台）

**🎯 A 档位 MVP 上线**：可邀请 3~5 家短剧/小说同行客户内测

### 阶段 4 — 平台适配器扩展（W10~W14）

- [ ] `BaseAdsAdapter` 完整接口
- [ ] TikTok / Meta 重构到新接口（W10）
- [ ] Google Ads 适配器（W11~W12）
- [ ] 巨量引擎适配器（W12~W13）
- [ ] Snapchat 适配器（W14）
- [ ] 每个适配器：list / write / insights / upload / OAuth 全覆盖
- [ ] 适配器单测 + Mock 回归

### 阶段 5 — 调度租户化 + 配额限流（W15~W16）

- [ ] APScheduler 所有 job 接 `tenant_id`
- [ ] `app_scheduled_jobs` 表驱动
- [ ] Redis 部署，`slowapi` per-tenant 限流
- [ ] `consume_quota` 装饰器接入所有付费路由
- [ ] 用量计数器 monthly cron

**条件触发** Celery 升级（若指标达标，本阶段或下阶段并入）

### 阶段 6 — 计费 Hybrid（W17~W20，**B 档位 MVP**）

- [ ] `app_plans` 种子数据 + 管理后台
- [ ] Stripe 集成（Checkout + Webhook + Billing Portal）
- [ ] 销售流：admin 后台手工开通
- [ ] 前端 `/settings/billing`、`/settings/api-keys`
- [ ] 自助注册 `/signup` + 邮箱验证
- [ ] 团队邀请 `/settings/team`

**🎯 B 档位 MVP 上线**：开放自助注册，正式商业化

### 阶段 7 — Onboarding / SSO / AI add-on（W21+）

- [ ] Google SSO（OIDC）
- [ ] 邀请链接 + 角色授予
- [ ] AI Studio 商业化（基于 `delivery_language.py` 扩展）
- [ ] 白标（自定义 logo / 主题色 / 子域名）
- [ ] 状态页 + 文档站 + 开发者门户

---

## 16. 风险登记册

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|---|
| R1 | DDL 全量变更锁表 | 中 | 高 | 维护窗口；大表用 `pt-online-schema-change`；分批 alter |
| R2 | Repository 改造漏掉 tenant 过滤 → 越权 | 中 | 严重 | CI lint；code review checklist；集成测试用两个 tenant 双跑 |
| R3 | OAuth refresh 失败致客户掉线 | 中 | 中 | refresh 提前 24h；失败通知客户；guard 重试 3 次 |
| R4 | APScheduler 单点崩溃 | 低 | 中 | systemd 自动重启；阶段 5 升级 Celery 时彻底解决 |
| R5 | MaxCompute / PolarDB 内部依赖泄漏到通用核心 | 中 | 中 | 插件化严格执行；CI 检测核心代码 `import plugins` 禁用 |
| R6 | 平台 API 限流共用导致雪崩 | 中 | 高 | per-tenant 限流；token bucket；指数退避 |
| R7 | 计费 webhook 漏处理导致客户白嫖 | 低 | 高 | webhook 幂等 + 重试；对账 job 每日比对 Stripe 与本地订阅 |
| R8 | AI 成本不可控 | 中 | 中 | 严格配额；高级模型按 token 计量；超额硬停 |
| R9 | 内部业务受改造影响 | 中 | 高 | 内部租户 = `tenant_id=1`，所有插件默认开启，行为不变；每阶段灰度 |
| R10 | 人力不足导致工期延期 | 中 | 中 | A 档位 MVP 先上线获得收入；B 档位按节奏延展 |

---

## 17. 验收标准（DoD）

### A 档位 MVP（W9）

- [ ] 内部租户业务行为与改造前 100% 一致（数据 + 功能回归）
- [ ] 可创建 ≥3 个外部租户，互相完全隔离（数据/凭证/审计）
- [ ] 外部租户可通过 OAuth 接入 TikTok + Meta，并完成一次完整同步
- [ ] 短剧业务相关菜单/路由在外部租户不可见
- [ ] 凭证全部加密存储，无明文残留
- [ ] 单测覆盖率 ≥60%（核心模块）

### B 档位 MVP（W20）

- [ ] 自助注册 → 完成订阅 → OAuth 接平台 → 拉取数据 全流程 < 10 分钟
- [ ] 至少 4 个平台适配器（TikTok/Meta/Google/巨量）覆盖 list + write + insights
- [ ] Stripe 订阅升降级、退订、支付失败全部走通
- [ ] 用量配额命中率监控可视化
- [ ] API Key 可对外提供，文档站基本可读

---

## 18. 关键指标（北极星）

| 指标 | A 阶段目标 | B 阶段目标 | 长期 |
|---|---|---|---|
| 活跃租户数（WAU） | 5 | 30 | 300+ |
| MRR | $1k | $10k | $100k+ |
| 平均接入时长 | < 1 天 | < 30 分钟 | < 5 分钟 |
| 同步成功率 | ≥98% | ≥99% | ≥99.5% |
| P95 API 延迟 | <500ms | <300ms | <200ms |
| Churn（月） | — | <5% | <3% |

---

## 19. 附录

### 19.1 名词表

| 术语 | 含义 |
|---|---|
| Tenant | 一个 SaaS 客户（公司/组织），数据隔离单位 |
| Workspace | 租户内的逻辑分组（一期暂不引入，预留） |
| Plugin | 可选业务模块（drama / optimizer / metis 等） |
| Adapter | 平台适配器（TikTok/Meta/Google 等） |
| Internal Tenant | `tenant_id=1`，AdsMind 自有短剧业务租户 |
| Quota | 套餐配额（API/AI/账户数等） |

### 19.2 涉及现有文件清单（改造范围）

**后端**：
- `backend/config.py` 增加 SaaS 配置
- `backend/auth.py` JWT 扩展 tenant
- `backend/db.py` 加密工具、DDL 改造
- `backend/app.py` plugin loader、生命周期
- `backend/routes/*.py` 全部接入 tenant 上下文
- `backend/repositories/*.py` 全部接收 tenant_id
- `backend/services/*.py` tenant_id 透传
- `backend/integrations/*` 完整重构
- `backend/tasks/*.py` job 接 tenant_id

**前端**：
- `frontend/src/contexts/AuthContext.tsx`
- `frontend/src/app/menu-config.ts`
- `frontend/src/app/router.tsx`
- `frontend/src/services/*.ts` 请求头注入
- 新增页面：onboarding、billing、team、integrations、api-keys

### 19.3 后续待办

- 评审会议（建议 2 小时）
- 锁定一期插件清单
- 定价市场调研
- KMS 选型（AWS / 阿里 / 自建 Vault）
- staging 环境采购

---

**评审通过后**，请按"阶段 0 准备" 任务列表创建对应 Issue / 排期，并以本文档为单一事实源（SSOT）持续迭代。

---

## 20. 阶段 1 落地记录（已实施）

> 提交时间：2026-05-15 · 状态：骨架就位，可灰度上线

### 20.1 已交付内容

| 模块 | 文件 | 说明 |
|---|---|---|
| 元数据表 DDL | `backend/db.py`（追加 8 张 SaaS 元数据表） | `app_tenants` / `app_tenant_members` / `app_plans` / `app_subscriptions` / `app_usage_counters` / `app_api_keys` / `app_oauth_credentials` / `app_scheduled_jobs` |
| 套餐种子 | `backend/db.py::_seed_default_plans` | 6 个默认套餐（internal / free / starter / pro / business / enterprise）幂等写入 |
| 内部租户种子 | `backend/db.py::_seed_internal_tenant` | 启动时确保 `id=1, slug='internal'` 的 internal 租户存在 |
| 租户上下文 | `backend/core/__init__.py` · `backend/core/tenant.py` | `TenantCtx` / `TenantMiddleware` / `get_current_tenant` / `require_plugin` / 查询工具 |
| 成员关系 Repository | `backend/repositories/tenant_member_repository.py` | `ensure_member` 幂等 upsert / `get` / `update_role` / `list_by_user` / `list_by_tenant` / `backfill_internal_members` 启动批量回填；全局 role → tenant_role 映射（admin → owner / 其它 → member） |
| User Repository | `backend/repositories/user_repository.py` | 新增 `get_by_id`（按 user.id 查询，便于跟成员表关联） |
| JWT 扩展 | `backend/auth.py` | `create_token` 增加 `tenant_id` / `tenant_slug` claim；`get_current_user` 兜底注入；旧 token 自动归属 internal tenant |
| 登录响应 | `backend/routes/users.py::login` | 登录时幂等写入成员关系；响应返回 `tenant.tenant_role` |
| 用户创建 | `backend/routes/users.py::add_user` | 创建新用户时自动加入当前 tenant（默认 internal） |
| 个人信息 | `backend/routes/users.py::me` | `/api/users/me` 返回 tenant + tenant_role |
| 启动钩子 | `backend/app.py::lifespan` | 调用 `backfill_internal_members` 一次性为现有 `app_users` 补齐 internal tenant 成员关系 |
| 中间件接入 | `backend/app.py::_setup_middleware` | 注册 `TenantMiddleware`（仅注入上下文，不阻断请求） |
| 前端 AuthContext | `frontend/src/contexts/AuthContext.tsx` | 新增 `tenant` 状态、`hasPlugin()` 方法、localStorage 持久化 |
| 前端登录页 | `frontend/src/pages/LoginPage.tsx` | 登录后保存 tenant 到 localStorage |
| 迁移生成器 | `backend/scripts/migrate/_generator.py` | 扫 `db.py` 自动生成 ALTER 脚本（不执行 DDL） |
| 正式迁移 | `backend/scripts/migrate/001_add_tenant_id.py` | 幂等执行 ALTER；支持 `--db app|biz|both` 和 `--dry-run` |

### 20.2 行为保证

- ✅ 现有用户登录后获得 `internal tenant (id=1)` 上下文，业务行为不变
- ✅ 旧 JWT（无 `tenant_id` claim）由中间件兜底降级，不会失效
- ✅ APP 库初始化时自动建表 + seed，重启即可获得 SaaS 元数据
- ✅ 业务表的 `tenant_id` 改造**未在启动时自动执行**，需手动调用迁移脚本（避免重启即破坏现有 schema）

### 20.3 验证步骤

```bash
# 1. 重启后端，检查启动日志
#    - "APP 应用库元数据表初始化完成"
#    - "已补充写入 6 条默认套餐种子"
#    - "已创建 internal 租户 (id=1)..."
cd backend && uvicorn app:app --reload

# 2. 预览迁移脚本（不执行 DDL）
python -m scripts.migrate._generator --db both --out /tmp/preview.sql

# 3. 干运行迁移（staging 环境）
python -m scripts.migrate.001_add_tenant_id --dry-run

# 4. 正式执行（仅在维护窗口）
python -m scripts.migrate.001_add_tenant_id

# 5. 前端登录后查 localStorage 应包含 auth_tenant
```

### 20.4 已知遗留 / 阶段 2 接续

- [x] ~~`app_users` 仍以 `username` 全局唯一；多租户成员关系由 `app_tenant_members` 承载，**当前未在 login 流程写入**~~ → **已完成**：登录、创建用户、启动回填三处都会幂等写入；详见 §20.5
- [ ] 业务表的 `tenant_id` 列迁移待人工在维护窗口执行
- [ ] 所有 repository 的 SQL 尚未携带 `tenant_id` 过滤（阶段 1 中间件只注入上下文，不强制隔离）
- [ ] 凭证仍为明文，AES-GCM 加密待阶段 2 实施
- [ ] OAuth 授权码流程待阶段 2 实施

### 20.6 阶段 2 落地（凭证安全 + OAuth 骨架）

> 提交时间：2026-05-15 · 状态：骨架就位，已通过加密 round-trip 自检

#### 已交付内容

| 模块 | 文件 | 说明 |
|---|---|---|
| 加密工具 | `backend/core/crypto.py` | AES-256-GCM；密文格式 `version(1)\|\|key_id(1)\|\|nonce(12)\|\|ciphertext\|\|tag(16)`；支持多密钥 keyring 轮换；`selftest()` 启动自检；`generate_key_b64()` 生成密钥 |
| 配置 | `backend/config.py` | 新增 `encryption_key_b64` / `oauth_redirect_base_url` / `oauth_state_secret` / `oauth_state_ttl_sec` |
| 依赖 | `backend/requirements.txt` | 显式声明 `cryptography>=42.0` |
| 凭证仓库 | `backend/repositories/oauth_credential_repository.py` | `upsert` / `get_access_token` / `get_refresh_token` / `get_meta` / `list_by_tenant` / `list_expiring` / `delete`；AAD 绑定 `tenant\|platform\|external_id` 防跨域重放 |
| OAuth 基类 | `backend/integrations/oauth_base.py` | `OAuthFlow` ABC、`TokenBundle` DTO、`build_state/verify_state` 自包含 HMAC state（无服务端存储）、`default_redirect_uri` |
| TikTok OAuth | `backend/integrations/tiktok/oauth.py` | `build_authorize_url` / `exchange_code` / `refresh`（refresh 抛 OAuthError，TikTok 不支持）；附带 `/oauth2/advertiser/get/` 拉广告主元信息 |
| Meta OAuth | `backend/integrations/meta/oauth.py` | 标准 OAuth2：code → short-lived → long-lived (60 天)；附带 `/me/adaccounts` 拉账户元信息 |
| 适配器工厂扩展 | `backend/integrations/base.py` | 新增 `get_oauth_flow(platform)` / `register_oauth_flow` / `supported_oauth_platforms`，为阶段 4 新增平台预留 |
| 集成路由 | `backend/routes/integrations.py` | `GET /api/integrations/platforms`、`/{platform}/oauth/start`、`/{platform}/oauth/callback`、`GET /credentials`、`DELETE /{platform}/credentials/{external_id}` |
| 启动自检 | `backend/app.py::lifespan` | 启动时调用 `crypto.selftest()`，未配置密钥时仅警告不阻断 |
| 路由注册 | `backend/app.py::_register_routers` | 加入 `integrations_router` |
| 迁移脚本 | `backend/scripts/migrate/002_encrypt_credentials.py` | 把 `biz_ad_accounts.access_token` 明文 → `app_oauth_credentials.access_token_enc`；支持 `--dry-run` 与 `--clear-plaintext` |

#### 行为保证

- ✅ 加密链路实测通过：明文 19 字节 → 49 字节密文，round-trip 一致（含中文）
- ✅ OAuth `state` 自包含 HMAC，TTL 10 分钟，服务端零状态
- ✅ 凭证 AAD = `tenant:{id}|platform:{p}|ext:{ext}`，跨租户密文不可解
- ✅ 多 advertiser/adaccount 场景下每个 external_id 独立落一份凭证（便于多账户独立续期）
- ✅ 未配置密钥时系统仍可启动（仅警告），保持向后兼容
- ✅ OAuth 回调端点**不依赖** JWT，身份由 state HMAC 还原

#### 验证步骤

```bash
# 0. 生成主密钥并写入 .env
python -c "from core.crypto import generate_key_b64; print(generate_key_b64())"
# 把输出粘贴到 .env：ENCRYPTION_KEY_B64=...

# 1. 启动后端，确认日志：
#    - "加密自检通过（AES-256-GCM）"
cd backend && uvicorn app:app --reload

# 2. 列出已实现 OAuth 的平台
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/integrations/platforms

# 3. 生成授权链接（前端拿 authorize_url 后开新窗口）
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/integrations/tiktok/oauth/start"

# 4. 干运行迁移现有 biz_ad_accounts 明文 → 加密表
python -m scripts.migrate.002_encrypt_credentials --dry-run

# 5. 正式迁移（先迁后清明文）
python -m scripts.migrate.002_encrypt_credentials
python -m scripts.migrate.002_encrypt_credentials --clear-plaintext  # 二次执行
```

#### 已知遗留 / 后续接续

- [x] ~~现有业务代码（`tiktok_ads/api/client.py` / `meta_ads/api/client.py`）仍从 `settings.tiktok_access_token` / `biz_ad_accounts.access_token` 取明文 token~~ → **已完成**：通过 `services/credential_service.py` 统一接入；详见 §20.7
- [ ] Refresh token 续期 job：当前 TikTok/Meta 都无原生 refresh，需要"过期前 14 天提醒重新授权"的 job + 通知
- [ ] 前端 `/settings/integrations` 页面：列表 + 一键授权（弹窗 + postMessage）+ 撤销
- [ ] 审计日志 `app_oplog` 加 `tenant_id` 字段
- [ ] Google Ads / 巨量引擎 / Snapchat 的 OAuth 实现（阶段 4）

### 20.7 阶段 2 补丁：业务代码接入加密凭证

> 提交时间：2026-05-15 · 状态：已落地，向后兼容

#### 解耦设计：三级降级

业务代码不再直接读 `settings.{platform}_access_token` 或 `biz_ad_accounts.access_token`，
全部通过 `services.credential_service` 统一入口取 token：

```
                ┌──────────────────────────────────────┐
                │  services.credential_service          │
                │  resolve_access_token(platform,       │
                │                       account_id,     │
                │                       tenant_id)      │
                └──────────────┬───────────────────────┘
                               │ 优先级（自顶向下）
        ┌──────────────────────┼──────────────────────────┐
        ▼                      ▼                          ▼
┌─────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐
│ Layer 1         │  │ Layer 2             │  │ Layer 3              │
│ app_oauth_      │  │ biz_ad_accounts     │  │ settings.{platform}_ │
│ credentials     │  │ .access_token       │  │ access_token         │
│ (AES-256-GCM)   │  │ (旧明文，兼容)       │  │ (.env 兜底)          │
└─────────────────┘  └─────────────────────┘  └──────────────────────┘
        │                      │                          │
        └───── OAuth flow ────┘                          └─ 本地开发
              (生产推荐)      (002 迁移期)
```

任意层有数据即返回；上游业务代码无需关心 token 实际从哪来。

#### 已交付内容

| 模块 | 文件 | 关键改动 |
|---|---|---|
| 凭证服务 | `backend/services/credential_service.py` | 新增 `resolve_access_token` / `resolve_token_source`，三级降级 |
| TikTok 客户端 | `backend/tiktok_ads/api/client.py` | `TikTokClient(access_token=None, account_id=None, tenant_id=None)`；未传 token 时自动走 credential_service；日志打印 token_source |
| Meta 客户端 | `backend/meta_ads/api/client.py` | 同上 |
| 投放路由 | `backend/routes/creatives.py` · `tiktok_materials.py` · `templates.py`（3 处） | 替换 `acc_row["access_token"]` → `resolve_access_token(...)`；错误提示语指引到 OAuth |
| Meta 资源 | `backend/routes/meta_assets.py` | `_get_token_for_account` 改为调用 credential_service |
| 素材服务 | `backend/services/tiktok_material_service.py` | `_get_token_for_advertiser` 同上 |
| 同步任务 | `backend/tasks/sync_campaigns.py` | 第 965 行 `acct.get("access_token")` 改为先走 credential_service，再降级到旧字段 |

#### 行为保证

- ✅ **完全向后兼容**：调用方显式传 `access_token` 时行为不变；未传时自动走加密表
- ✅ **迁移期容错**：未跑 002 迁移、`app_oauth_credentials` 为空时，自动降级到旧明文字段
- ✅ **本地开发友好**：仍可只配 `.env` 跑通（Layer 3 兜底）
- ✅ **日志可观测**：每次 client 初始化都打印 `token_source`，运维可一眼判断生产已升级到加密表
- ✅ **零路径破坏**：所有原 `TikTokClient()` / `MetaClient()` 无参调用保持兼容

#### 调用示例

```python
# 旧写法（仍兼容）
client = TikTokClient(access_token=row["access_token"])

# 新写法（推荐：让 client 自己解析）
client = TikTokClient(account_id=advertiser_id, tenant_id=tenant.id)

# 服务/路由先取 token 再判错（适合需要给前端友好错误的场景）
from services.credential_service import resolve_access_token
token = resolve_access_token("tiktok", account_id=advertiser_id, tenant_id=tenant.id)
if not token:
    raise HTTPException(400, "未找到 access_token，请先完成 OAuth 授权")
client = TikTokClient(access_token=token, account_id=advertiser_id)
```

#### 冒烟测试

```bash
$ python -c "from services.credential_service import resolve_access_token; \
             from tiktok_ads.api.client import TikTokClient; \
             from meta_ads.api.client import MetaClient; \
             from integrations.base import supported_oauth_platforms; \
             print('platforms =', supported_oauth_platforms())"
platforms = ['tiktok', 'meta']
```

所有模块导入正常；TikTok / Meta 授权 URL 构造正常；state HMAC round-trip 通过。

---

### 20.5 成员关系扫尾说明

#### 写入触发点（三处）

| 触发点 | 时机 | 写入内容 | 幂等性 |
|---|---|---|---|
| `app.py::lifespan` 启动钩子 | 服务每次启动 | 遍历所有 `app_users`，幂等写入到 `(internal_tenant, user.id)`；角色按 `super_admin/admin → owner` / 其它 → `member` 映射 | `INSERT IGNORE` |
| `routes/users.py::login` | 每次成功登录 | 当前 user 写入 `(internal_tenant, user.id)`，role 同上 | `INSERT IGNORE` |
| `routes/users.py::add_user` | admin 通过 API 创建新用户 | 新用户加入当前请求所在 tenant（阶段 1 即 internal） | `INSERT IGNORE` |

三处都包了 try/except，**失败不阻断登录或创建流程**（向后兼容尚未运行迁移的环境）。

#### 角色映射

```
global user.role               →   tenant_role
─────────────────────────────────────────────
super_admin                    →   owner
admin                          →   owner
optimizer / designer / analyst →   member
viewer / 其它                   →   member
```

后续阶段 6 引入真正多租户后，每个 tenant 会有独立的 RBAC，可以脱离 global role 单独配置。

#### API 响应增量

- `POST /api/users/login` 响应中 `tenant` 对象新增 `tenant_role` 字段
- `GET /api/users/me` 响应中 `tenant` 对象新增 `tenant_role` 字段（优先取 `app_tenant_members.role`，缺失则用 global role 映射兜底）

#### 验证步骤

```bash
# 启动后查询成员表，应该看到与 app_users 同样的行数
mysql> SELECT COUNT(*) FROM adpilot_app.app_users;
mysql> SELECT COUNT(*) FROM adpilot_app.app_tenant_members WHERE tenant_id = 1;

# 登录后查 /me，tenant.tenant_role 应该是 owner 或 member
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/users/me
```

---

## 21. 阶段 3 落地（业务插件化）

> 完成时间：2026-05-18 · 状态：批次 1 已上线 · 关联 PR：（待提）

阶段 3 把"短剧业务专属"代码从核心路径剥离到 `backend/plugins/`，让外部租户只看到通用核心；
内部租户（`tenant_id=1`）行为完全不变。整体分三批推进：

| 批次 | 范围 | 状态 |
|---|---|---|
| 批次 1 | 插件基础设施 + drama / optimizer / designer_performance | ✅ 已上线 |
| 批次 2 | attribution_metis（含 blend_service）+ ops_panel | ⏳ 待启动 |
| 批次 3 | returned_conversion + 同步任务事件 hook | ⏳ 待启动 |

### 21.1 插件基础设施

#### `plugins/base.py` — `Plugin` 抽象 + `HookHub`

```python
@dataclass
class PluginMeta:
    name: str                                       # 与 app_tenants.enabled_plugins 对齐
    label: str = ""
    version: str = "0.1.0"
    panels: list[str] = field(default_factory=list) # 关联前端 panelKey
    requires_env: list[str] = field(default_factory=list)
    requires_db: list[str] = field(default_factory=list)


class Plugin(ABC):
    meta: PluginMeta

    def is_available(self, settings) -> bool: ...   # 默认按 requires_env 检查
    def register_routes(self, app) -> None: ...     # app.include_router(router, prefix="/api")
    def register_jobs(self, scheduler, settings) -> None: ...
    def register_hooks(self, hub: HookHub) -> None: ...


class HookHub:
    """轻量级事件总线，批次 3 用 sync_campaigns.emit("after_tiktok_ad_report", ...) 接入。"""
    def subscribe(self, event: str, handler): ...
    def emit(self, event: str, **kwargs): ...       # 单个 handler 异常被吞掉
```

#### `core/plugin_loader.py` — 启动期调度

两步入场（保持启动顺序清晰）：

```python
# Step 1：app 创建后立即调用，注册可用插件的路由
register_routes(application)
# Step 2：lifespan startup 内调用（此时 scheduler 已就绪）
register_jobs_and_hooks(scheduler, settings)
```

不可用（缺依赖）的插件会被跳过并记录日志；单个插件异常被捕获，不影响其它插件或主流程。

### 21.2 批次 1 已交付内容

#### 新增目录

```
backend/plugins/
├─ __init__.py
├─ base.py                              # Plugin / PluginMeta / HookHub
├─ drama/                               # 短剧分析
│   ├─ __init__.py
│   ├─ plugin.py                        # DramaPlugin 注册入口
│   ├─ routes.py                        # ← routes/drama.py
│   ├─ repository.py                    # ← repositories/drama_repository.py
│   ├─ sync_job.py                      # ← tasks/sync_drama.py
│   └─ name_parser.py                   # ← tasks/drama_name_parser.py
├─ optimizer/                           # 优化师人效 + 名单
│   ├─ __init__.py
│   ├─ plugin.py                        # OptimizerPlugin 注册入口
│   ├─ routes_performance.py            # ← routes/optimizer_performance.py
│   ├─ routes_directory.py              # ← routes/optimizer_directory.py
│   ├─ repository_performance.py        # ← repositories/optimizer_performance_repository.py
│   ├─ repository_directory.py          # ← repositories/optimizer_directory_repository.py
│   ├─ sync_job.py                      # ← tasks/sync_optimizer.py
│   └─ name_parser.py                   # ← tasks/optimizer_name_parser.py
└─ designer_performance/                # 设计师人效
    ├─ __init__.py
    ├─ plugin.py
    ├─ routes.py                        # ← routes/designer_performance.py
    └─ repository.py                    # ← repositories/designer_performance_repository.py
```

#### 修改文件

| 文件 | 改动 |
|---|---|
| `backend/app.py` | 删除 4 个旧 router 显式 import（drama / optimizer × 2 / designer_performance）；`_register_routers` 末尾调用 `plugin_loader.register_routes`；lifespan 内调用 `register_jobs_and_hooks`；`_sync_all_job` 内的 sync_drama / sync_optimizer import 改走 `plugins.*.sync_job`（保持调度行为完全一致） |
| `backend/core/plugin_loader.py` | 新增 |
| `backend/plugins/**` | 新增（见上） |
| `frontend/src/types/menu.ts` | `MenuItem` 增加 `pluginKey?: string` |
| `frontend/src/app/menu-config.ts` | `designer-performance` / `drama-analysis` / `optimizer-performance` / `optimizer-directory` 4 项追加 `pluginKey` |
| `frontend/src/components/layout/sidebar.tsx` | `filterMenu` 接受 `hasPlugin`；panelKey 与 pluginKey 双重校验（AND） |

#### Shim 兼容层（12 个文件）

每个旧路径文件被改为 4 行重定向 shim：

```python
"""阶段 3 批次 1 shim — 原内容已迁至 plugins.drama.repository。"""
import sys
from plugins.drama import repository as _impl
sys.modules[__name__] = _impl
```

`sys.modules` 重定向后，外部代码无论用 `from repositories import drama_repository`、
`from repositories.drama_repository import foo`、还是 `drama_repository._private_helper` 都能正确拿到。

涉及文件：

| 原路径 | shim → 实际模块 |
|---|---|
| `backend/repositories/drama_repository.py` | `plugins.drama.repository` |
| `backend/repositories/optimizer_performance_repository.py` | `plugins.optimizer.repository_performance` |
| `backend/repositories/optimizer_directory_repository.py` | `plugins.optimizer.repository_directory` |
| `backend/repositories/designer_performance_repository.py` | `plugins.designer_performance.repository` |
| `backend/tasks/sync_drama.py` | `plugins.drama.sync_job` |
| `backend/tasks/drama_name_parser.py` | `plugins.drama.name_parser` |
| `backend/tasks/sync_optimizer.py` | `plugins.optimizer.sync_job` |
| `backend/tasks/optimizer_name_parser.py` | `plugins.optimizer.name_parser` |
| `backend/routes/drama.py` | `plugins.drama.routes` |
| `backend/routes/optimizer_performance.py` | `plugins.optimizer.routes_performance` |
| `backend/routes/optimizer_directory.py` | `plugins.optimizer.routes_directory` |
| `backend/routes/designer_performance.py` | `plugins.designer_performance.routes` |

**移除时间窗**：1~2 周后（约 2026-06-01）统一清理 shim，到时把项目内的 `from repositories.drama_repository` / `from tasks.sync_drama` 等替换为 `plugins.*` 路径。

### 21.3 行为保证

- **路由 URL 完全不变**：仍是 `/api/drama/*` / `/api/optimizer-performance/*` / `/api/optimizer-directory/*` / `/api/designer-performance/*`，前端零改动
- **调度任务行为完全不变**：`_sync_all_job` 调用 sync_drama / sync_optimizer 的窗口、频率、传参一致
- **内部租户（tenant_id=1）**：`_INTERNAL_FALLBACK.enabled_plugins` 默认包含 `drama / optimizer / designer_performance`，菜单和 API 全开
- **外部租户**：未启用插件时菜单消失（前端 `hasPlugin()` 过滤）；批次 2 会补 `require_plugin` Depends 让 API 也返回 404
- **shim 不会重复实例化**：`sys.modules[__name__] = _impl` 让旧路径与新路径完全是同一个模块对象（`is` 等价）

### 21.4 验证

冒烟自检结果（启动期日志 + Python 自检脚本）：

```
✓ 插件 drama 路由已注册               4 个路由 (/api/drama/{summary,locale-breakdown,trend,sync})
✓ 插件 optimizer 路由已注册           15 个路由 (/api/optimizer-performance/* + /api/optimizer-directory/*)
✓ 插件 designer_performance 路由已注册 2 个路由 (/api/designer-performance/{summary,materials})
插件路由注册完成: {'drama': 'routes_ok', 'optimizer': 'routes_ok', 'designer_performance': 'routes_ok'}
API 路由总数: 160
```

12 个 shim 用 `assert drama_repository is plugins.drama.repository` 全数通过。
前端 `tsc --noEmit` 零错误。

### 21.5 批次 2 启动前清单（attribution_metis + ops_panel）

下次接续时按以下顺序进行（不要跳步）：

1. **解耦 blend_service 与核心 `routes/biz.py`**
   - `biz_attribution_service` / `biz_blend_service` / `dms_client.py` 整体迁入 `plugins/attribution_metis/`
   - `routes/biz.py` 14 处 `biz_attribution_service.*` / `biz_blend_service.*` 调用改造为 plugin-aware：插件启用时正常调用；未启用时降级到 legacy normalized 口径（只读 `biz_*_normalized` 表）
2. **drama / optimizer 反向依赖处理**
   - `plugins/drama/repository.py` 3 处 `from services.biz_blend_service import _attr_subquery`
   - `plugins/optimizer/repository_performance.py` 1 处同上
   - 迁完 blend_service 后改为 `from plugins.attribution_metis.blend_service import _attr_subquery`，并增加 `try/except ImportError` 降级到无归因模式
3. **ops_panel 整体迁移**
   - 6 个 ops repository / service + 4 个 sync 任务 → `plugins/ops_panel/`
   - `routes/ops.py` 改 shim
   - `app.py` 的 4 个 ops cron job 改由 `OpsPlugin.register_jobs` 负责（首次让插件真正使用调度接口）
4. **菜单**：`ops-dashboard` 加 `pluginKey: 'ops_panel_polardb'`；attribution 相关菜单同步
5. **验收**：内部租户 24h 灰度对账（归因图表 / 运营面板行数）；外部租户 `/api/biz/*` 自动降级 legacy 口径

---

## 22. 阶段 4 落地（应用配置模块）

> 完成时间：2026-05-19 · 状态：X1~X5 已上线 + X3-filter（业务查询接入）已闭环

阶段 4 在 `Tenant` 之下引入一层 `Application`（产品/App），让单个租户能拆出多个应用独立运营，
为后续 SaaS 化场景（一家公司同时投多款 App / 多个国家版本）打基础。

### 22.1 已交付内容

- **数据库**
  - `app_applications` / `app_application_members` 两张元数据表（DDL 在 `db.py`）
  - 迁移 `003_add_application_id.py`：给 `biz_ad_accounts` 和 `app_oauth_credentials` 加 `application_id` 列与索引，
    回填 internal tenant 历史数据到 default application（**已执行**：`biz_ad_accounts` 回填 26 行）
  - 启动期为每个 active tenant 自动 `ensure_default_for_tenant`（`is_default=1`），保证旧数据始终有归属
- **后端**
  - `core/application.py`：`ApplicationCtx` / `ApplicationMiddleware` / `get_current_application` / `require_application_role`
  - `repositories/application_repository.py`：CRUD + 成员管理 + slug 唯一性
  - `routes/applications.py`：`/api/applications/*` 全套 REST（list / get / create / update / archive / restore / 成员 / 广告账号绑定解绑）
  - `auth.py`：JWT 增加可选 `application_id` claim；`UserOut` 暴露 `id` / `email` 供前端调度
  - `biz_account_repository.py`：新增 `list_by_application` / `list_with_application_for_tenant` / `bind_to_application`，
    且 `_application_id_column_exists()` 做兼容兜底
- **前端**
  - `AuthContext` 扩展 `application` / `applications` 状态与 `switchApplication`，并写入 `localStorage.current_application_id`
  - `apiFetch` 自动给所有请求加 `X-Application-Id` 头
  - 侧边栏 `ApplicationSelector` 切换器；`ApplicationsListPage` / `ApplicationDetailPage`（基本信息 / 广告账号 / 归因回传 / 成员四 tab）

### 22.2 X3-filter 落地（业务查询真正按 application 过滤）

X3 阶段把"应用上下文"打通到业务查询层，闭环"切应用看到不同数据"的产品语义。

**核心规则（已在 `routes/accounts.py::_filter_by_application` 落地）**

| 当前应用类型 | 查询行为 | 原因 |
|---|---|---|
| `is_default=1`（租户默认应用） | **不传 `application_id`，全租户视角** | 兼容内部租户既有"看见全部 26 个账号"的历史链路 |
| 非默认应用 | **严格按 `application_id` 过滤** | 真正的应用维度隔离 |

**代码变更**

- `repositories/biz_account_repository.py`
  - `list_all(application_id=None)` / `list_by_platform(platform, application_id=None)` / `list_active(application_id=None)`
    新增 `application_id` 可选参数 + `_application_id_column_exists()` 兜底
- `services/account_service.py`
  - `list_accounts(platform, application_id=None)` 透传
  - `add_account(..., application_id=None)`：新建账号时如果当前是非默认应用，自动调用 `bind_to_application` 绑定
- `routes/accounts.py`
  - `GET /api/ad-accounts/` 注入 `application = Depends(get_current_application)`，按 `_filter_by_application(application)` 决定是否过滤
  - `POST /api/ad-accounts/` 自动归属到当前非默认应用
  - 返回体新增 `application_id` / `application_name` / `filtered` 字段，便于调试与前端 UI 提示
- `routes/applications.py`
  - 修复 `ApplicationOut` / `MemberOut` / `AdAccountOut` 的 `created_at` / `updated_at` / `joined_at` / `last_synced_at`
    类型校验：用 `@field_validator(..., mode="before")` 自动把 `datetime` 转 ISO8601 字符串，避免 `ResponseValidationError`

**端到端冒烟（已通过）**

| 用例 | `X-Application-Id` | 期望 | 实际 |
|---|---|---|---|
| 不带头 | — | 全部 26 个 | 26 ✓ |
| default app | `1` | 26（不过滤） | 26 ✓ |
| smoke-test-app + 绑定 1 个账号 | `2` | 1（仅绑定的那个） | 1 ✓ |
| 切回 default | `1` | 仍是 26 | 26 ✓ |

输出 `PASS  N0=26  N1=26  N2=1  N3=26`。

### 22.3 行为保证

- **内部租户旧链路 0 影响**：所有用户登录后默认落到 default application（`is_default=1`），
  查询走"全租户视角"，跟阶段 4 之前 100% 一致
- **后台任务不过滤**：`tasks/sync_*.py` / `services/credential_service.py` 调用的是 `list_active()`（不传 application_id），
  仍是租户级遍历，保证同步覆盖率与现有口径一致
- **细节查询接口（按账号 ID 取详情）不过滤**：`get_by_platform_account` / `get_by_id` 不引入 application 条件，
  避免破坏 `routes/templates.py` / `routes/creatives.py` 中已经按账号 ID 精确定位的链路
- **优雅降级**：`_application_id_column_exists()` 检查列是否存在，
  若 003 迁移未跑过则自动跳过过滤，杜绝"漏跑迁移导致接口 500"的事故

### 22.4 X3-filter Round 2 落地（业务报表接口应用化）

> 完成时间：2026-05-19 · 状态：6 个高频接口已接入；剩余 7 个接口待 Round 3

**设计动机**：`routes/biz.py` 共 13 个查询接口，原本都接受单值 `account_id` 过滤参数。
直接扩 service / repository 签名为 `account_ids: list[str]` 涉及 30+ 函数，风险大。
Round 2 改在 **route 层**做"应用账号白名单守门"，0 改动 service 层。

**规则表（已在 `core/biz_filter.py::resolve_account_filter` 落地）**

| 当前应用 | 用户传 `account_id`? | 应用下账号数 | 行为 |
|---|---|---|---|
| 默认应用 | — | — | 透传，行为完全不变 |
| 非默认 | 否 | 0 | `skip_query=True` → 返回空 + `_hint: '未绑定任何广告账号'` |
| 非默认 | 否 | 1 | 自动注入唯一账号 ID |
| 非默认 | 否 | ≥ 2 | `skip_query=True` → 返回空 + `_hint: '请指定 account_id'` |
| 非默认 | 是 | — | 校验在白名单内，否则 **403** |

**已接入的 6 个接口**

| 接口 | 返回结构 | skip_query 形状 |
|---|---|---|
| `GET /api/biz/overview` | dict (聚合指标) | `{"_source", "_hint", "_application_id"}` |
| `GET /api/biz/campaign-agg` | list | `data=[], _hint, _application_id` |
| `GET /api/biz/campaign-daily` | dict (分页) | `data={"list": [], "total": 0, "_hint", ...}` |
| `GET /api/biz/top-campaigns` | list | 同 campaign-agg |
| `GET /api/biz/adgroup-daily` | dict (分页) | 同 campaign-daily |
| `GET /api/biz/ad-daily` | dict (分页) | 同 campaign-daily |

**端到端冒烟（已通过）**

| 用例 | 期望 | 结果 |
|---|---|---|
| 默认应用 + 不传 account_id | 真数据 + 无 `_hint` | ✓ `_source=blend` |
| 非默认应用 + 0 账号 | `_hint='未绑定任何广告账号'` | ✓ |
| 非默认应用 + 1 账号 + 不传 | 自动注入 + 真数据 | ✓ |
| 非默认应用 + 错误 account_id | HTTP 403 | ✓ |
| 非默认应用 + 正确 account_id | 真数据 | ✓ |
| 6 接口在空账号应用下都返回 `_hint` | 全部为 True | ✓ 6/6 |

### 22.5 后续待办

- **X3-filter Round 3**（可选）：把过滤下沉到剩余 7 个接口
  - `biz_campaigns` / `biz_adgroups` / `biz_ads`：列表型，需先取应用账号再用 `account_id IN (...)` 过滤
  - `biz_adgroup_aggregated` / `biz_ad_aggregated` / `creative_analysis`：不接受 `account_id`，需要按 platform 查应用账号后改 service 签名
  - 当前阶段先保留"租户级"语义，待外部租户实际使用时再下沉
- **前端 UI 配套**：检测响应里的 `_hint` 字段，在面板顶部展示提示条
- **X4 - 配额与计费维度**：应用级别的额度（账号数 / 调用 QPS / 日同步条数）打通到 `app_quotas` 表
- **X5 - 应用级 OAuth 凭证**：当前 OAuth 凭证已加 `application_id` 列，待 OAuth 回调路径写入与读取打通

## 23. 阶段 7：租户自助注册（SaaS 客户第一公里）

> 目标：让外部 SaaS 客户**无需内部人员介入**，自助开通账号、创建租户、播种默认应用，并在 5 分钟内进入 Onboarding 引导。

### 23.1 端到端流程

`
新用户 GET /register
   ↓
填表（邮箱 + 密码 + 公司名 + 套餐）
   ↓
POST /api/auth/register
   ↓
后端单一事务：
  1) 校验邮箱唯一 / 公司名 slug 唯一
  2) INSERT app_tenants (status=active, plan_id=free, is_internal=0,
                          enabled_plugins=['core_ads'])
  3) INSERT app_users (role='admin', username=email)
  4) INSERT app_tenant_members (role='owner')
  5) INSERT app_applications (is_default=1, name='<公司名> 默认应用')
  6) create_token(tenant_id=new, application_id=new)
   ↓
前端写 localStorage + navigate('/dashboard')
   ↓
Dashboard 检测空 _hint → 展示 OnboardingChecklist 三步引导
`

### 23.2 API 契约

POST /api/auth/register

| 入参 | 类型 | 必填 | 说明 |
|---|---|---|---|
| email | string | 是 | 联系邮箱，规整为 lowercase；同时作为登录 username |
| password | string | 是 | ≥ 8 位 |
| company_name | string | 是 | 用于 tenant.name；slug 自动生成 |
| plan_id | string | 否 | free / pro / biz / enterprise，默认 free |
| display_name | string | 否 | 缺省取 email 前缀 |

响应（成功）：

\\\json
{
  "ok": true,
  "token": "<jwt>",
  "user": { "id": 14, "username": "...", "role": "admin", ... },
  "tenant": { "id": 4, "slug": "...", "name": "...", "plan_id": "free", "tenant_role": "owner" },
  "application": { "id": 17, "slug": "default", "name": "... 默认应用", "is_default": true },
  "allowed_panels": [...27 项],
  "next_step": "bind_ad_account"
}
\\\

失败情况：
- HTTP 422 + `邮箱 <x> 已被注册`
- HTTP 422 + 密码长度不足 / 邮箱格式错误（pydantic）
- HTTP 500 + 用户创建异常（会回滚已创建的 tenant）

### 23.3 多租户数据隔离加固

发现 X3-filter 原有的"默认应用 = 全量视角"规则在多租户场景下会**跨租户泄露**（新租户的默认应用能看到内部 26 个账号）。

修复（`routes/accounts.py::_filter_by_application` + `core/biz_filter.py`）：

| 应用归属 | 是否默认 | 过滤行为 |
|---|---|---|
| **internal tenant（id=1）** | 是 | 全量视角，行为不变（兼容内部历史链路） |
| internal tenant | 否 | 严格按 application_id 过滤 |
| **外部租户** | **是 / 否** | **严格按 application_id 过滤**（不再享受默认应用豁免） |

冒烟覆盖：
- 内部 admin 登录 → 仍看到 26 个账号 ✓
- 新注册外部租户 → `/api/ad-accounts/` 返回 0；`/api/biz/overview` 返回 `_hint` ✓

### 23.4 `users.py::login` 升级

阶段 1 写死了 `tenant_id = INTERNAL_TENANT_ID`，阶段 7 改为按 `app_tenant_members` 智能选择：

1. 用户加入的**非 internal** 租户（多个时取最早加入的）
2. 用户加入的 internal 租户
3. 都没有 → 兜底 internal + 幂等补一条成员关系

这样：
- 外部租户的 owner 登录后立即进入自己的租户上下文
- 内部员工登录后仍是 internal tenant（行为不变）
- 旧账号首次登录会自动加入 internal tenant

### 23.5 前端配套

| 文件 | 变更 |
|---|---|
| `pages/RegisterPage.tsx` | 新增：表单 + 三档套餐对比 + 自动登录跳转 |
| `pages/LoginPage.tsx` | 底部加 "立即注册试用" 链接 |
| `app/router.tsx` | 注册 `/register` 路由（不进 MainLayout，无须鉴权） |

### 23.6 安全 & 后续待办

**MVP 阶段已落地：**
- 邮箱格式 + 密码长度校验
- 邮箱唯一性
- slug 自动唯一化（`星辰科技` → `xing-chen-ke-ji` → `xing-chen-ke-ji-2`）
- 用户创建失败时回滚租户

**待后续阶段补：**
- [ ] 邮箱验证码 / magic link（防止邮箱滥注册）
- [ ] reCAPTCHA / IP 速率限制（防机器人）
- [ ] 套餐配额（accounts_limit / api_calls_monthly）落地到 `app_quotas` + middleware 校验
- [ ] 付费套餐选择 → 接入支付（Stripe / 微信支付）
- [ ] 邀请同事加入租户（生成 invite token）
- [ ] 租户 owner 转让 / 注销账号

## 24. 阶段 7：配额限流 MVP

> 目标：让套餐字段真正生效。Free 租户最多 1 个应用 / 1 个广告账号，超额返回 422 + 升级提示。Internal 租户完全豁免。

### 24.1 配额来源

- 套餐表：`app_plans`（已有 6 档 seed：internal / free / starter / pro / business / enterprise）
- 应用数、成员数上限：从 `app_plans.features` JSON 读取（`applications_limit` / `members_limit`），如果 features 没填则用 `plan_repository._DEFAULT_*_LIMIT_BY_PLAN` 兜底
- 账号数上限：直接读 `app_plans.accounts_limit` 列

| Plan | applications | accounts | members |
|---|---|---|---|
| internal | 999 | 999 | 999 |
| free | **1** | **1** | **1** |
| starter | 3 | 3 | 5 |
| pro | 10 | 10 | 20 |
| business | 30 | 30 | 100 |
| enterprise | 999 | 999 | 999 |

### 24.2 守门策略

| 调用点 | 检查函数 | internal 豁免 |
|---|---|---|
| POST /api/applications | `enforce_application_quota` | ✓ |
| POST /api/applications/{id}/ad-accounts/bind | `enforce_account_quota` | ✓ |
| POST /api/ad-accounts/（直接新建） | `enforce_account_quota` | ✓ |

账号 distinct 计数：同一个 `account_id` 在多个应用下绑定不重复计数（`existing_account_id` 参数）。

### 24.3 错误协议

超额时返回 HTTP 422：

\\\json
{
  "detail": {
    "code": "QUOTA_EXCEEDED_APPLICATIONS",
    "message": "当前套餐「free」最多可创建 1 个应用（已用 1）",
    "used": 1,
    "limit": 1,
    "plan_id": "free",
    "upgrade_hint": "升级到 Starter / Pro 套餐解锁更多额度"
  }
}
\\\

错误码：
- `QUOTA_EXCEEDED_APPLICATIONS`
- `QUOTA_EXCEEDED_ACCOUNTS`
- `QUOTA_EXCEEDED_MEMBERS`（预留，本批未启用）

### 24.4 `GET /api/quota/me`

返回当前租户的"配额视图"：

\\\json
{
  "tenant_id": 6,
  "is_internal": false,
  "plan_id": "free",
  "plan_name": "Free",
  "limits": { "applications": 1, "accounts": 1, "members": 1,
              "api_calls_monthly": 5000, "ai_calls_monthly": 0 },
  "usage":  { "applications": 1, "accounts": 1, "members": 1 },
  "exhausted": { "applications": true, "accounts": true, "members": true }
}
\\\

### 24.5 前端集成

| 文件 | 变更 |
|---|---|
| `services/api.ts` | 新增 `QuotaExceededError`；422 + detail.code='QUOTA_EXCEEDED_*' 时统一抛此错误 |
| `services/quota.ts` | 新增 `getMyQuota()` |
| `components/common/QuotaUsageCard.tsx` | 新组件：套餐 + 三个指标进度条 + 超额时变橙色 + 升级 CTA；internal tenant 自动隐藏 |
| `pages/ApplicationsListPage.tsx` | 顶部接入 QuotaUsageCard；create 失败捕获 QuotaExceededError 友好提示 |
| `pages/ApplicationDetailPage.tsx` | 绑定账号失败捕获 QuotaExceededError 友好提示 |

### 24.6 多租户安全加固

发现 `routes/accounts.py::add_account` 在外部租户的默认应用下新建账号时把 `application_id` 留 NULL，导致：
1. 用户刚建完账号马上"看不见"（X3-filter 按 application_id 过滤）
2. 配额计数失准（count_accounts 遍历应用 + list_by_application，漏掉 NULL）

修复逻辑：
- `internal tenant` + 默认应用 → 保持 NULL（兼容历史"全租户视角"）
- 其它所有情况（含外部租户默认应用）→ 强制绑定 `application_id`

### 24.7 后续待办

- [ ] 在创建应用按钮 / 绑定账号按钮上根据 `exhausted` 实时禁用（当前只在提交后报错）
- [ ] `app_usage_counters` 接入 `api_calls_monthly` 限流（middleware 计数 + 月度滚动）
- [ ] 升级套餐流程：创建支付订单 → Stripe webhook → `app_subscriptions.plan_id` 切换
- [ ] 套餐降级 grace period：超额数据软暂停，提示用户清理或升级
## 25. 阶段 7：团队邀请流程

> 目标：让 SaaS 客户能把同事拉进自己的租户，不依赖内部人员手工建账号。

### 25.1 端到端流程

\\\
owner 进 /team 页 → 点"邀请成员"
   ↓
填邮箱 + 角色 (owner/admin/member) + 有效期
   ↓
POST /api/tenant/invitations
   ↓
后端校验：
  - 不能给自己 / 已是成员 / 重复邀请
  - members 配额 (含 pending) 不超额
  - 生成 token = secrets.token_urlsafe(32)
   ↓
返回 invitation_url
   ↓
owner 复制链接发给同事 (邮件 / IM 自行决定)
   ↓
同事打开 /invitation/:token
   ↓
GET /api/auth/invitation/:token （匿名）→ tenant_name / inviter / role / email_registered
   ↓
分支：
  - 邮箱已注册 + 未登录 → 引导去登录后回来
  - 邮箱已注册 + 已登录 + 匹配 → 一键接受
  - 邮箱未注册 → 表单 (密码 + 显示名) + 接受
  - 登录账号 ≠ 受邀邮箱 → 提示退出后重打开
   ↓
POST /api/auth/invitation/:token/accept
   ↓
后端事务：创建 user (若需要) + ensure_member(tenant, user, role)
         + mark_accepted + 签 token(tenant_id, default_application_id)
   ↓
前端写 localStorage + 跳 /dashboard
\\\

### 25.2 表结构 `app_tenant_invitations`

| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| tenant_id | BIGINT | 目标租户 |
| email | VARCHAR(255) | 受邀邮箱 (lowercase) |
| role | VARCHAR(50) | owner / admin / member |
| token | VARCHAR(64) UNIQUE | URL token (32 字节 URL-safe) |
| expires_at | DATETIME | 默认 7 天，1-30 天可调 |
| accepted_at / accepted_user_id | DATETIME / BIGINT | 接受后填充 |
| invited_by_user_id | BIGINT | 谁发的 |
| revoked_at | DATETIME | 撤销时间 |
| created_at | DATETIME | |

状态机由 `invitation_repository._row_status` 派生：`active / accepted / revoked / expired`。

### 25.3 API 一览

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | /api/tenant/invitations | admin | 发起邀请；返回 invitation_url |
| GET | /api/tenant/invitations | admin | 列出本租户全部邀请（含历史） |
| DELETE | /api/tenant/invitations/:id | admin | 撤销邀请 (active → revoked) |
| GET | /api/auth/invitation/:token | 匿名 | 预览：tenant 名 / 邀请人 / 受邀邮箱 / email_registered |
| POST | /api/auth/invitation/:token/accept | 匿名或登录 | 接受邀请，返回 JWT |

### 25.4 错误码

| HTTP | detail.code | 触发 |
|---|---|---|
| 422 | INVITATION_ALREADY_PENDING | 同 email 已有 active 邀请 |
| 422 | INVITATION_NOT_ACTIVE | accept 时邀请非 active (accepted/revoked/expired) |
| 422 | EMAIL_MISMATCH | 登录账号 ≠ 受邀邮箱 |
| 422 | LOGIN_REQUIRED | 受邀邮箱已注册但未登录 |
| 422 | PASSWORD_REQUIRED | 新用户接受时未传 password |
| 422 | QUOTA_EXCEEDED_MEMBERS | 配额超额（含 pending） |
| 404 | "邀请不存在或链接无效" | token 不存在 |

### 25.5 配额联动

- `quota_service.get_usage` 新增 `usage.pending_invitations` 字段
- `exhausted.members` 现在等于 `members + pending_invitations >= members_limit`
- 这样 owner 在 free 套餐（members=1）只能邀请 0 人（自己已占 1），符合直觉

### 25.6 前端

| 文件 | 作用 |
|---|---|
| `services/invitations.ts` | list / create / revoke / preview / accept |
| `pages/InvitationAcceptPage.tsx` | 匿名接受页 `/invitation/:token`；自动判别"已登录 / 需注册 / 邮箱不匹配"四态 |
| `pages/TeamPage.tsx` | 邀请管理页 `/team`：邀请列表 + 复制链接 + 撤销 + 配额卡 |
| `app/router.tsx` | 注册 `/invitation/:token` (无须 auth) 和 `/team` (panelKey=team) |
| `app/menu-config.ts` | 系统管理菜单加"团队成员"项 |
| `db.py` `_PANEL_SEED` | 新增 `team` panel；super_admin / admin 自动获权 |

### 25.7 后续待办

- [ ] 实际寄出邀请邮件（接 SendGrid / SES，目前只生成链接靠 owner 自己发）
- [x] 成员列表（已加入）单独展示 + 改角色 / 移除 → 见 §26
- [ ] 邀请链接二维码（移动端扫码加入）
- [ ] 邀请数量提速限制（防 owner 一次性发 1000 个）
- [ ] members 配额超额时禁用"邀请成员"按钮（当前依赖提交后报错）

---

## 26. 阶段 7：成员管理（已加入成员）

> 目标：租户 owner/admin 在团队页管理**已加入**成员，与 §25 的「待接受邀请」并列。

### 26.1 API

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/tenant/members` | tenant admin | 列出本租户成员（user_id / username / display_name / role / joined_at） |
| PUT | `/api/tenant/members/{user_id}` | tenant admin | 改角色 `owner \| admin \| member` |
| DELETE | `/api/tenant/members/{user_id}` | tenant admin | 移除成员 |

保护规则（`routes/invitations.py`）：

- 不能移除自己；不能把**最后一个 owner** 降级或踢出
- 不能把 owner 降为 member（须先指定另一名 owner）

### 26.2 前端

- `TeamPage.tsx`：`members` / `invites` 两个 Tab；`MemberRow` 支持改角色、移除
- `services/invitations.ts`：`listTenantMembers` / `updateMemberRole` / `removeTenantMember`

---

## 27. 阶段 7：付费升级闭环（MVP，无 Stripe）

> 不接支付网关；租户提交申请 → **internal 租户**上的平台 `admin`/`super_admin` 审批 → 直接改 `app_tenants.plan_id`。

### 27.1 表 `app_plan_upgrade_requests`

| 列 | 说明 |
|---|---|
| tenant_id / from_plan_id / to_plan_id | 申请方与目标套餐 |
| contact_email / message | 联系信息 |
| status | `pending` → `approved` \| `rejected` \| `cancelled` |
| processed_by_user_id / admin_note / processed_at | 审批痕迹 |

### 27.2 API

**租户侧**（`require_admin` + 当前 tenant）：

- `POST /api/billing/upgrade-request`
- `GET /api/billing/upgrade-requests`
- `POST /api/billing/upgrade-request/{id}/cancel`

**平台侧**（`_require_platform_admin`：**须 `tenant.is_internal` 且** 用户角色为 `admin`/`super_admin`）：

- `GET /api/billing/admin/upgrade-requests`
- `POST .../{id}/approve` — 事务内更新 tenant.plan_id
- `POST .../{id}/reject`

> 注意：SaaS 注册用户在 `app_users.role` 也为 `admin`，但所属租户非 internal，**不能**访问平台审批接口。

### 27.3 前端

| 组件 | 作用 |
|---|---|
| `QuotaUsageCard` + `UpgradePlanDialog` | 配额用尽时「升级套餐」→ 填目标套餐与留言 |
| `UpgradeRequestsPage` | internal 管理员审批列表（菜单：套餐升级审批） |

---

## 28. 阶段 7：邮箱验证（MVP，无真实发信）

### 28.1 数据

- `app_email_verifications`：注册时写入 token（默认 24h 有效）
- `app_users.email_verified_at`：验证成功后打时间戳

### 28.2 API

| Method | Path | 说明 |
|---|---|---|
| — | 注册响应 `email_verification.verification_url` | MVP 在 UI 弹窗展示链接（不发邮件） |
| GET/POST | `/api/auth/verify-email/{token}` | 验证；重复验证返回 `already_verified` |
| POST | `/api/auth/resend-verification` | 登录后发新 token |
| GET | `/api/users/me` | `email_verified`：有 `email_verified_at` → true；有 pending → false；历史用户无记录 → true |

### 28.3 前端

- `RegisterPage`：注册成功展示验证链接
- `VerifyEmailPage`：`/verify-email/:token`
- `EmailVerifyBanner`：未验证时顶栏提示 + 重发

---

## 29. 阶段 7：客户级 OAuth（TikTok / Meta，含 Mock）

### 29.1 流程

1. 应用详情「广告账号」Tab → 选择平台 → `GET /api/integrations/{platform}/oauth/start?application_id=…`
2. `state.extra.a` 携带应用 id；回调后 `account_service.add_account(..., application_id=…)` 绑定
3. 未配置 `tiktok_app_id` / `meta_app_id` 时返回 `mock_mode: true` + `mock_authorize_url`
4. `GET .../oauth/mock-callback`：写入 2 个演示账号 + 凭证，完成绑定

### 29.2 前端

- `services/integrations.ts`：`startOAuth` / `openOAuthWindow`
- `ApplicationDetailPage` AccountsTab：OAuth 授权按钮

### 29.3 冒烟

`backend/_smoke_combined.py` 串联 §26–§29 四项；本地需先启动 `uvicorn app:app --port 5000`。

---

## 30.5 阶段 7 P0 加固（邮件 / 限流 / OAuth 中心 / 隔离审计）

> 完成时间：2026-05-20 · 状态：已上线

### 30.5.1 邮件 `services/email_service.py`

- `EmailSender` 抽象 + 3 个 backend：`console`（默认）/ `smtp` / `disabled`
- 启用方式（`backend/config.py`）：`email_backend=smtp` 并配置 `smtp_host` 等
- 业务模板：`send_verify_email` / `send_invitation_email`
- 集成点：
  - `routes/registration.py::register` 注册成功后真发验证邮件
  - `routes/registration.py::resend_verification` 重发同样走真邮件
  - `routes/invitations.py::create_invitation` 邀请生成后真发邮件
- 失败语义：邮件发送异常**只记日志、不阻断主流程**，前端响应里 `email_delivery` 字段说明本次走了哪个 backend / 是否失败

### 30.5.2 速率限制 `core/rate_limit.py`

进程内 token bucket，按 (scope, IP) 维度限流。`X-Forwarded-For` 优先（nginx 部署友好）。

| 端点 | scope | 默认值 |
|---|---|---|
| `POST /api/auth/register` | register | 20 / hour / IP |
| `POST /api/users/login` | login | 10 / minute / IP |
| `POST /api/auth/resend-verification` | email_send | 30 / hour / IP |
| `POST /api/tenant/invitations` | email_send | 30 / hour / IP |

命中时返回 HTTP 429 `{detail: {code, message, retry_after_sec}}` + `Retry-After` header。

### 30.5.3 生产环境密钥硬检查

`backend/app.py::lifespan` 启动时若 `APP_ENV=production`：

- 未配置 `ENCRYPTION_KEY_B64` → **启动失败**
- `crypto.selftest()` 失败 → 启动失败
- `jwt_secret_key=change-me-in-production` → **启动失败**

非生产环境（默认）：未配置密钥时自动生成临时密钥并 WARN，与之前行为一致。

### 30.5.4 集成中心 `/settings/integrations`

- 后端聚合接口 `GET /api/integrations/overview` 返回每个平台的：是否配置真实凭证、mock 可用性、`{total, valid, expiring, expired}`
- 前端 `pages/IntegrationsPage.tsx` 提供一键授权 + 凭证列表 + 撤销操作
- 菜单：系统管理 → 集成中心（panelKey=`applications`）

### 30.5.5 OAuth 凭证过期扫描 `tasks/oauth_credential_alerts.py`

- 调度：每日 03:20（启动后 8 分钟跑首扫）
- 规则：已过期 → `EXPIRED` 通知；14 天内 → `EXPIRING` 通知
- 去重：`app_oauth_alerts` 表，7 天内同凭证 + 同状态不重复发
- 通知对象：租户内 role ∈ {owner, admin} 的成员邮箱

### 30.5.6 跨租户越权审计

| 攻击面 | 加固后行为 |
|---|---|
| `X-Tenant-Id` 与 JWT 不一致 | 加固：以 JWT 为准；header 不同时 warning 后丢弃 |
| `X-Application-Id` 指向他租户 application | 加固：忽略并降级到本租户 default + warning 日志 |
| 业务报表接口未按 application 过滤 | 已通过 `core/biz_filter.resolve_account_filter` 在 6 个高频接口落地；其它 7 个接口走 X3 Round 3 |
| 13 个 `biz_*_repository.py` 中只有 `biz_account_repository.py` 含 `tenant_id` | **已知遗留**：当前业务表 schema 未全量加 `tenant_id` 列；事实上的隔离靠 application → account_id 白名单实现。完整 `001_add_tenant_id` 迁移在维护窗口执行后，需补 repository 改造（见 §15 阶段 1 待办） |

### 30.5.7 公网 base URL `public_base_url`

邮件 / 邀请链接的优先级：`settings.public_base_url` > `request.origin` > `request.host` > 相对路径。生产部署须显式设置 `PUBLIC_BASE_URL=https://app.example.com` 才能在邮件里给出可点链接。

---

## 30. 阶段 7 批次验收清单（1–4）

| # | 能力 | 本地验证 |
|---|---|---|
| 1 | OAuth mock | 应用详情 → TikTok/Meta 授权 → 出现 2 个 mock 账号 |
| 2 | 升级 | 配额卡申请 → `admin` 登录 → 套餐升级审批 → 通过 → `GET /api/quota/me` 套餐变更 |
| 3 | 邮箱 | `/register` → 复制验证链接 → `/verify-email/:token` → 顶栏 banner 消失 |
| 4 | 成员 | `/team` → 已加入成员 Tab → 改角色 / 移除（注意 owner 保护） |

内部账号：`admin` / `admin123`（internal 租户，可审批升级）。

