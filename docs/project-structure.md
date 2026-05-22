# AdsMind 项目结构说明

```
adpilot/
├─ backend/          # Python 后端（FastAPI）
├─ frontend/         # React 前端（Vite + TypeScript）
├─ scripts/          # 诊断/审计/回填等运维脚本
├─ deploy/           # 部署配置模板
├─ docs/             # 项目文档
├─ .env              # 环境变量（不提交到 Git）
└─ .gitignore
```

## backend/

FastAPI 后端应用，从 `backend/` 目录启动。

| 目录/文件 | 职责 |
|-----------|------|
| `app.py` | 应用入口，路由注册，定时任务调度 |
| `auth.py` | JWT 认证，用户鉴权 |
| `config.py` | 环境变量读取（pydantic-settings） |
| `db.py` | 数据库连接池，表初始化，数据迁移 |
| `routes/` | API 路由层（按资源划分） |
| `repositories/` | 数据访问层（SQL 操作） |
| `services/` | 业务逻辑层 |
| `schemas/` | Pydantic 数据模型 |
| `tasks/` | 后台同步任务（Meta/TikTok 数据拉取） |
| `integrations/` | 平台适配器（统一接口抽象） |
| `meta_ads/` | Meta Marketing API 客户端 |
| `tiktok_ads/` | TikTok Marketing API 客户端 |
| `static/` | 后端静态文件 |

### 数据库架构

| 库 | 变量前缀 | 用途 | 权限 |
|----|----------|------|------|
| PRD (`matrix_advertise`) | `PRD_MYSQL_*` | 产研基础数据 | 只读 |
| APP (`adpilot_app`) | `APP_MYSQL_*` | 系统元数据 | 读写 |
| BIZ (`adpilot_biz`) | `BIZ_MYSQL_*` | 业务报表数据 | 读写 |

## frontend/

React SPA 前端，使用 Vite 构建。

| 目录/文件 | 职责 |
|-----------|------|
| `src/` | 源代码（页面、组件、服务、路由） |
| `public/` | 公共静态资源 |
| `vite.config.ts` | 构建配置，开发代理 |
| `dist/` | 构建产物（gitignored） |

前端通过 `/api` 相对路径调用后端，开发时由 Vite proxy 转发，生产环境由 Nginx 反向代理。

## scripts/

运维和诊断脚本，按用途分类。这些脚本不属于正式后端服务，仅用于手动排查和数据修复。

| 子目录 | 用途 |
|--------|------|
| `diagnostics/` | 数据诊断、面板排查 |
| `audits/` | 数据审计（Meta/剧级对账） |
| `backfill/` | 数据回填与重建 |
| `misc/` | 其他工具（部署、连接测试等） |

## deploy/

服务器部署配置模板，不含真实密钥。

| 文件 | 用途 |
|------|------|
| `nginx/adpilot.conf.example` | Nginx 站点配置 |
| `systemd/adpilot.service.example` | systemd 服务配置 |
| `env/backend.env.example` | 后端环境变量模板 |
| `env/frontend.env.example` | 前端环境变量模板 |

## docs/

| 文件 | 内容 |
|------|------|
| `deployment.md` | 服务器部署完整流程 |
| `local-development.md` | 本地开发启动指南 |
| `project-structure.md` | 本文件 |
| `saas-transformation.md` | 通用广告 SaaS 改造方案（草案 v1.0） |
