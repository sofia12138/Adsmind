#!/bin/bash
set -e

SERVER="admin@47.237.67.41"
DEPLOY_SCRIPT="/opt/adpilot/deploy/update.sh"

echo "[1/2] 推送代码到 GitHub..."
git push origin main

echo ""
echo "[2/2] 触发服务器部署..."
ssh "$SERVER" "bash $DEPLOY_SCRIPT"
