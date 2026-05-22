#!/bin/bash
set -e

PROJECT_DIR="/opt/adpilot"
STATIC_DIR="/var/www/adpilot"

cd "$PROJECT_DIR"

echo "========================================"
echo "  AdsMind 一键部署"
echo "========================================"
echo ""

echo "[1/5] 拉取最新代码..."
git pull origin main
echo ""

echo "[2/5] 安装后端依赖..."
source .venv/bin/activate
pip install -r backend/requirements.txt --quiet
echo ""

echo "[3/5] 构建前端..."
cd frontend
npm install --prefer-offline --no-audit --no-fund
NODE_OPTIONS="--max-old-space-size=4096" npm run build
cd ..
echo ""

echo "[4/5] 更新静态文件..."
sudo rm -rf "$STATIC_DIR"/*
sudo cp -r frontend/dist/* "$STATIC_DIR"/
sudo chown -R www-data:www-data "$STATIC_DIR"
echo ""

echo "[5/5] 重启后端服务..."
sudo systemctl restart adpilot
sleep 5
echo ""

echo "========================================"
echo "  部署完成"
echo "========================================"
sudo systemctl status adpilot --no-pager | head -8
echo ""
echo "Health check:"
curl -s --max-time 10 http://127.0.0.1:8000/health || echo "(服务仍在启动中，请稍后手动检查)"
echo ""
