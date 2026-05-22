# AdsMind 本地开发指南

## 前置条件

- Python 3.11+
- Node.js 18+
- MySQL 8.0+（本地或远程）
- 已创建本地数据库 `adpilot_app` 和 `adpilot_biz`

## 1. 环境变量

在项目根目录创建 `.env` 文件（参考 `deploy/env/backend.env.example`）：

```bash
cp deploy/env/backend.env.example .env
# 编辑 .env 填入实际值
```

## 2. 后端启动

```bash
# 安装依赖
pip install -r backend/requirements.txt

# 启动（从 backend/ 目录）
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

后端运行在 `http://localhost:8000`，首次启动会自动初始化数据库表。

## 3. 前端启动

```bash
cd frontend
npm install
npm run dev -- --port 4000 --host 0.0.0.0
```

前端运行在 `http://localhost:4000`，Vite 会自动将 `/api` 代理到 `http://127.0.0.1:8000`。

## 4. 外网访问（可选）

如需通过外网访问（如移动端调试）：

```bash
ngrok http 4000 --url=<YOUR_NGROK_DOMAIN>
```

前端 `vite.config.ts` 已配置 `allowedHosts: ['.ngrok-free.dev']`。

## 5. 常见排查

### 后端启动报数据库连接错误
- 确认 MySQL 服务运行中
- 确认 `.env` 中 APP_MYSQL_* 和 BIZ_MYSQL_* 配置正确
- 确认数据库 `adpilot_app` 和 `adpilot_biz` 已创建

### 前端显示网络错误
- 确认后端已启动并监听 8000 端口
- 检查 `vite.config.ts` 中 proxy 目标是否为 `http://127.0.0.1:8000`

### 前端编译错误
```bash
cd frontend
rm -rf node_modules
npm install
```

### 手动触发数据同步
```bash
# 通过 API 触发
curl -X POST "http://localhost:8000/api/sync/trigger?days=3"
```
