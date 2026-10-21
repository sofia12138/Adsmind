# CutFlow 入口接入

AdsMind「素材中心 → 自动剪辑」在新标签页打开独立运行的 CutFlow。
入口沿用「素材库」权限，不传递 AdsMind 的令牌、租户或应用信息。
CutFlow 的访问权限由其部署环境控制；菜单权限不会替代 CutFlow 自身的访问控制。
当前成片需从 CutFlow 导出，再通过 AdsMind 的素材上传流程用于广告创建。

## 配置

在 `frontend/.env.local` 中设置完整的 HTTP 或 HTTPS 地址：

```dotenv
VITE_CUTFLOW_URL=https://cutflow.your-domain.com/series
```

修改配置后，开发环境重启前端；生产环境重新构建并部署前端。
生产环境未配置地址，或配置无效时，入口显示待配置说明。
仅从本机访问的开发环境默认使用 `http://localhost:5173/series`。
从局域网、远程浏览器访问时，应配置浏览器可访问的 CutFlow 地址。

## 两个项目同时在本机运行

CutFlow 默认使用 API 4000、前端 5173；AdsMind 前端也默认使用 4000。
同时运行时，将 AdsMind 前端改用 4200，避免端口冲突：

```bash
# AdsMind/frontend
npm run dev -- --port 4200

# CutFlow 项目根目录（须先完成该项目的环境配置）
npm run dev
```

AdsMind 后端继续使用 8000。打开 AdsMind 后，在「素材中心」点击「自动剪辑」。
CutFlow 需要单独启动；仅配置入口不会启动其 API、数据库或剪辑 worker。
