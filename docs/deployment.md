# AdsMind 服务器部署指南

## 前置条件

- Ubuntu 20.04+ 服务器
- Python 3.11+
- Node.js 18+ (构建前端)
- MySQL 8.0+（APP 库 + BIZ 库）
- Nginx
- 已创建数据库：`adpilot_app`、`adpilot_biz`
- 已有产研库 `matrix_advertise` 的只读访问权限

## 1. 拉取代码

```bash
cd /var/www
git clone <REPO_URL> adpilot
cd adpilot
```

## 2. 配置环境变量

```bash
cp deploy/env/backend.env.example .env
nano .env  # 填入实际的数据库密码、API Key 等
```

**重要**：`.env` 放在项目根目录 `/var/www/adpilot/.env`，后端 `config.py` 通过 `../.env` 向上读取。

## 3. 后端部署

### 3.1 创建 Python 虚拟环境

```bash
cd /var/www/adpilot
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 3.2 验证后端启动

```bash
cd backend
uvicorn app:app --host 127.0.0.1 --port 8000
# 确认 Application startup complete 后 Ctrl+C 退出
```

### 3.3 配置 systemd 服务

```bash
sudo cp deploy/systemd/adpilot.service.example /etc/systemd/system/adpilot.service
sudo nano /etc/systemd/system/adpilot.service
# 修改 <USER> 为实际用户名，确认路径正确

sudo systemctl daemon-reload
sudo systemctl enable adpilot
sudo systemctl start adpilot
```

### 3.4 查看后端日志

```bash
sudo journalctl -u adpilot -f          # 实时日志
sudo journalctl -u adpilot --since today  # 今日日志
sudo systemctl status adpilot            # 服务状态
```

## 4. 前端部署

### 4.1 构建前端产物

```bash
cd /var/www/adpilot/frontend
npm install
npm run build
# 产物输出到 frontend/dist/
```

### 4.2 验证构建产物

```bash
ls frontend/dist/index.html  # 确认文件存在
```

## 5. 配置 Nginx

```bash
sudo cp deploy/nginx/adpilot.conf.example /etc/nginx/sites-available/adpilot.conf
sudo nano /etc/nginx/sites-available/adpilot.conf
# 修改 <YOUR_DOMAIN>；root 需与静态资源实际目录一致（一键部署脚本将 dist 拷到 /var/www/adpilot）

sudo ln -s /etc/nginx/sites-available/adpilot.conf /etc/nginx/sites-enabled/
sudo nginx -t        # 检查配置
sudo systemctl reload nginx
```

**Nginx 代理逻辑**（详见仓库内 `deploy/nginx/adpilot.conf.example`）：
- `/` → 前端静态文件，SPA 回退到 `index.html`
- `/api/materials/tiktok/` → 单独加长超时与 body 限制（大视频上传必需）
- `/api/` → 反向代理到 `http://127.0.0.1:8000/api/`
- `/health`、`/docs`、`/openapi.json` → 后端

## 6. 数据库说明

| 库名 | 用途 | 权限 |
|------|------|------|
| `matrix_advertise` (PRD) | 产研基础数据 | **只读** |
| `adpilot_app` (APP) | 系统元数据：用户、权限、模板、面板配置 | 读写 |
| `adpilot_biz` (BIZ) | 业务数据：报表、同步日志、回传转化 | 读写 |

后端首次启动时会自动创建 APP 和 BIZ 库所需的表结构。

## 7. 更新部署

### 方式一：一键部署（推荐）

本地执行，自动推送代码并触发服务器更新：

```bash
bash deploy/remote-deploy.sh
```

该脚本会依次执行：`git push` → SSH 到服务器 → 运行 `deploy/update.sh`

### 方式二：服务器手动执行

SSH 登录服务器后运行：

```bash
bash /opt/adpilot/deploy/update.sh
```

`update.sh` 会自动完成：拉取代码 → 安装后端依赖 → 构建前端 → 更新静态文件 → 重启服务

### 方式三：逐步手动更新

```bash
cd /opt/adpilot
git pull origin main

# 后端更新
source .venv/bin/activate
pip install -r backend/requirements.txt
sudo systemctl restart adpilot

# 前端更新
cd frontend
npm install
npm run build
sudo rm -rf /var/www/adpilot/*
sudo cp -r dist/* /var/www/adpilot/
```

### 回滚

```bash
cd /opt/adpilot
git log --oneline -10                  # 查看历史版本
git checkout <commit-hash> -- .        # 回退到指定版本
bash deploy/update.sh                  # 跳过 git pull，直接重建部署
```

## 8. 常见问题

### 后端启动失败
```bash
sudo journalctl -u adpilot -n 50 --no-pager  # 查看最近 50 行日志
```

### .env 读取失败
确认 `.env` 位于 `/var/www/adpilot/.env`（项目根目录），后端从 `backend/` 目录通过 `../.env` 读取。

### 数据库连接失败
确认 MySQL 服务运行中，且 `.env` 中的数据库连接信息正确。APP 和 BIZ 库需在本机或可达的 MySQL 实例上预先创建。

### TikTok 素材上传提示「网络错误」或网关超时

单条上传请求会持续到「浏览器传完文件 + 后端转发 TikTok API 完成」。若 Nginx 使用默认或较短的 `proxy_read_timeout`（如 120s）、`client_body_timeout`（默认 60s），连接会被提前断开，浏览器 XHR 常表现为「网络错误」。

**处理**：用仓库中的 [deploy/nginx/adpilot.conf.example](deploy/nginx/adpilot.conf.example) 覆盖或合并到线上配置，确保至少包含：

- `client_max_body_size`、`client_body_timeout`、`send_timeout` 足够大
- `location ^~ /api/materials/tiktok/` 内 `proxy_read_timeout` / `proxy_send_timeout` 设为 3600s 左右

修改后执行：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

**自查**：`sudo tail -f /var/log/nginx/error.log`，上传失败时若出现 `upstream timed out` 或 `client timed out`，即为超时问题。
