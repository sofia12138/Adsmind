# AdsMind — 广告投放管理系统

多平台（Meta / TikTok）广告投放管理系统，支持广告创建、模板管理、数据同步、回传分析、资产库管理等功能。

## 项目结构

```
adpilot/
├─ backend/       # FastAPI 后端（API、数据库、同步任务）
├─ frontend/      # React 前端（Vite + TypeScript + TailwindCSS）
├─ scripts/       # 运维脚本（诊断/审计/回填）
├─ deploy/        # 部署配置模板（Nginx / systemd / env）
├─ docs/          # 项目文档
├─ .env           # 环境变量（不提交到 Git）
└─ .gitignore
```

详细结构说明见 [docs/project-structure.md](docs/project-structure.md)。

平台执行预检、dry-run 与外部写入隔离契约见 [docs/platform-preflight.md](docs/platform-preflight.md)。

## 本地开发

### 后端

```bash
pip install -r backend/requirements.txt
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev -- --port 4000 --host 0.0.0.0
```

前端通过 Vite proxy 将 `/api` 请求代理到 `http://127.0.0.1:8000`。

详细本地开发指南见 [docs/local-development.md](docs/local-development.md)。

## 环境变量

复制模板并填入实际值：

```bash
cp deploy/env/backend.env.example .env
```

主要配置项：
- **三库连接**：PRD（只读产研库）、APP（系统元数据）、BIZ（业务数据）
- **平台 API**：Meta / TikTok Marketing API 密钥
- **JWT 认证**：Secret Key、过期时间
- **CORS**：允许的前端域名

详见 [deploy/env/backend.env.example](deploy/env/backend.env.example)。

## 服务器部署

完整部署流程见 [docs/deployment.md](docs/deployment.md)。

部署配置模板：
- Nginx：[deploy/nginx/adpilot.conf.example](deploy/nginx/adpilot.conf.example)
- systemd：[deploy/systemd/adpilot.service.example](deploy/systemd/adpilot.service.example)

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+ / FastAPI / Uvicorn / PyMySQL |
| 前端 | React 18 / TypeScript / Vite / TailwindCSS / TanStack Query |
| 数据库 | MySQL 8.0（三库架构） |
| 平台集成 | Meta Marketing API / TikTok Marketing API |
