# AdsMind 部署配置

本目录包含服务器部署所需的示例配置文件。

## 目录结构

```
deploy/
├─ nginx/
│  └─ adpilot.conf.example    # Nginx 站点配置模板
├─ systemd/
│  └─ adpilot.service.example # systemd 服务配置模板
└─ env/
   ├─ backend.env.example     # 后端环境变量模板
   └─ frontend.env.example    # 前端环境变量模板
```

## 使用方式

1. 将 `env/backend.env.example` 复制为项目根目录的 `.env`，填入实际配置
2. 将 `nginx/adpilot.conf.example` 复制到 `/etc/nginx/sites-available/`，修改域名和路径
3. 将 `systemd/adpilot.service.example` 复制到 `/etc/systemd/system/`，修改用户和路径

详细部署流程参见 [docs/deployment.md](../docs/deployment.md)。
