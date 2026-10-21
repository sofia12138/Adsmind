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

## 投放操作台与广告草稿

TikTok / Meta 操作台现在支持账户筛选、服务端搜索与分页。日期、账户、搜索、排序和页码保存在 URL 中，刷新或分享链接可保留查询条件。顶部指标按账户和日期统计，搜索只影响广告系列列表。默认查询最近 7 天。

操作台使用 `/api/biz/console/{campaign|adgroup|ad}`，返回当前页数据及对应对象的状态和预算，不再让前端加载整个平台的全部结构数据。查询继续采用现有 blend / attribution / legacy 聚合口径，并校验应用的账户范围。目前分页在聚合结果上完成；极大数据量下仍可继续优化各数据源的 SQL 分页。

新建广告时先保存草稿和模板快照，再展示配置预检查及创建确认。可选择「仅保存草稿」，后续在「投放管理 → 广告草稿」继续。草稿按租户、应用和创建人隔离。

创建表单和草稿展示所选账户币种，预算不进行汇率换算。新草稿提交 `budget_currency`，服务端与所属账户再次核对；未声明币种的历史草稿只有 USD 账户可继续，其余先编辑确认。Meta 暂支持 USD、EUR、CNY，沿用整数金额单位 x100；其他币种须独立核实平台规则后开放，不能使用默认单位猜测。正数及最多两位小数的预算校验在保存修改和执行时生效。

未执行的 DRAFT 支持编辑广告系列名称、TikTok 日预算、Meta CBO 广告系列预算或 ABO 各广告组预算。修改保留素材、定向与模板快照，并更新版本号；旧版本更新、跨团队/应用/创建人修改、修改已执行草稿均被拒绝。尚不支持在编辑器中替换素材或修改定向，修改这些配置需要重新建立草稿。

`app_launch_drafts` 在后端启动时幂等建表。每个创建步骤先记录待确认状态，再调用平台；成功结果立即保存。继续失败的草稿时，已经成功的相同步骤会复用平台返回结果。

网络超时、进程中断等可能造成平台已接受写入但本地没有确认结果。此时草稿标为 UNKNOWN，或保留 RUNNING / PENDING，系统阻止重复写入，必须先核对真实平台。当前版本没有自动回查或人工补录平台编号的流程，不应直接重置这些状态后再次创建。

配置预检查校验账户属于当前应用，并要求账户本地状态为 ACTIVE；停用、暂停或缺失状态时阻止创建。账户相关检查失败时，确认页可前往数据源配置处理，草稿保留。账户状态以最近一次同步记录为准，不代替平台的实时限制、素材审核、余额、预算下限及能力检查。创建状态仍沿用模板。修改过的真实投放链路须在受控账户单独验证；本地测试不创建真实广告。

验证命令：

```bash
cd frontend
npm run build
npm test

cd ../backend
../.venv/bin/python -m unittest discover -s tests -v

# 使用当前本地开发数据库验证持久化与失败恢复；平台响应被模拟。
# 临时测试草稿使用独立的测试创建人，结束后自动清理。
ADSMIND_INTEGRATION_TESTS=1 ../.venv/bin/python -m unittest discover -s tests -v
```

## 多租户隔离（共享系统与数据库）

客户在 `/register` 注册团队，系统创建租户、默认应用和所有者。成员通过团队邀请加入；登录后侧栏显示当前团队。租户身份来自服务端验证后的 JWT，并在每次请求中重新校验有效成员关系。租户停用、成员移除、无效应用或跨租户应用请求都会被拒绝。

`core/isolation.py` 为 API 提供统一身份边界。模板、广告资产、素材记录、账户与日志的单表 CRUD 通过受限的租户查询适配器执行；适配器不支持复杂 SQL，遇到不支持的语句直接拒绝。报表通过所属广告账户过滤。租户 1 的默认应用也不再具有查看所有租户广告账户的权限。业务数据账户 ID 全局唯一，因此同一个平台广告账户当前只允许归属一个租户；跨租户再次接入返回冲突，不能覆盖原凭证。

后台广告同步按活跃租户依次运行；手动同步只访问当前应用账户。同步状态按租户保存，仍为单进程内存状态，重启后重置；多实例部署前需替换为数据库或任务队列锁。短剧、内部归因、运营数据等自有数据源只允许内部租户使用，不作为客户共享资源。

手动添加的 Access Token 写入租户绑定的加密凭证表，App Secret 使用租户/平台/账户绑定的加密值。请求不再回退使用环境中的全局默认凭证。历史明文凭证仍保留兼容读取，正式迁移现有线上数据时应单独完成历史凭证加密与清理，不能把未知归属记录直接分配给客户。

启动迁移只新增租户归属字段和索引，历史资源默认归内部租户。启动时自动补齐成员关系仅限 `admin` / `superadmin` 两个内置账号；其余没有成员关系的历史账号须显式确认归属后迁移，不会自动获得内部租户访问权。登录/退出时清理前端查询缓存，避免切换身份后残留前一团队的数据。

`tests/test_tenant_isolation.py` 使用两个自动清理的临时租户验证身份伪造、跨应用访问、账户覆盖、成员管理、模板/资产读写、凭证回退、素材、日志、同步状态、报表和广告草稿隔离。平台网络调用不参与测试。

### TikTok 本地接入

新团队从首页引导进入「数据源配置 → 添加账户」，在本地填写 Access Token、App ID 和 App Secret。三个字段均必填，不使用其他团队或环境中的应用凭证。授权列表由 `/oauth2/advertiser/get/` 读取，币种和时区由 `/advertiser/info/` 读取，缺失时阻止连接，避免默认为 USD / UTC。接口形状参考 [TikTok 官方 SDK](https://github.com/tiktok/tiktok-business-api-sdk/blob/main/python_sdk/docs/AccountManagementApi.md)。

前端通过 `POST /api/ad-accounts/connect` 保存；服务端再次核对账号是否属于凭证授权范围，并以平台信息覆盖客户端传入的名称、币种、时区。凭证仍写入当前租户加密存储，账号绑定当前应用。免费团队每次最多选择一个账号，实际账号总数由服务端配额控制。多账号部分成功时，成功项从待提交列表移除，剩余项可以继续处理。

保存后在数据源页手动点击「立即同步」，读取当前应用账户的结构和投放日报，不创建平台广告。模拟平台接口与本地租户测试已覆盖元数据读取、授权范围重验、跨租户隔离和敏感信息脱敏；真实平台凭证仍需由用户填写后联调。客户团队隐藏平台内部的套餐审批菜单。

### 本地密码恢复

`services.password_recovery.issue(user_id, email)` 供可信本地管理员生成 30 分钟有效的一次性链接；数据库仅存令牌摘要。用户在 `/reset-password#token=...` 自行设置密码，服务端在同一事务内更新密码并消费令牌。无自助邮件申请入口，不能向未验证的请求者自动返回恢复链接。当前实现不会撤销之前签发的 JWT；正式部署前需要补齐会话撤销及通过已验证邮箱发送恢复邮件的流程。

### TikTok / Meta 官方授权连接

「数据源配置 → 授权连接」进入集成中心。运营方在服务端配置 `TIKTOK_APP_ID`、`TIKTOK_APP_SECRET`、`OAUTH_REDIRECT_BASE_URL` 和 `PUBLIC_BASE_URL`；客户不用填写开发者密钥。TikTok 开发者后台登记的回调地址必须与 `${OAUTH_REDIRECT_BASE_URL}/api/integrations/tiktok/oauth/callback` 一致，正式域名使用 HTTPS。默认本地前端为 `http://localhost:4001`，后端回调为 `http://localhost:8000/api/integrations/tiktok/oauth/callback`；平台是否接受本地回调须在开发者后台实际确认，不能把本地测试当成正式授权联调。

启动迁移创建 `app_oauth_sessions`。授权会话绑定发起管理员、租户和当前应用，10 分钟有效；回调核对签名 state 与数据库摘要、检查管理员成员关系，并通过条件更新阻止重放。兼容 TikTok 返回的 `auth_code`。换取的凭证只在服务端加密保存，回跳前端只携带随机会话 ID；账号选择接口不返回 Token。授权后用户选择一个账号，服务端检查本次授权范围及套餐配额，将账号绑定当前应用，并清除临时凭证密文。需要连接更多账号时重新发起授权。

Meta 使用相同的一次性会话及账号选择流程，服务端配置 `META_APP_ID` 和 `META_APP_SECRET`，回调登记为 `${OAUTH_REDIRECT_BASE_URL}/api/integrations/meta/oauth/callback`。请求 `ads_read`、`ads_management`，并核对实际获批权限；分页读取 `/me/adaccounts`，保留平台返回的币种、时区和账号状态。Token 有效期以平台响应为准。授权会话也绑定平台，不能在 TikTok 和 Meta 之间混用。HTTP 请求及回调日志中的授权码、Token、Secret 和 state 做脱敏处理。

取消、过期、无账号或平台错误需要重新连接。两个平台未配置开发者应用时显示不可用，不自动创建演示账号。真实 TikTok / Meta 授权需配置各自开发者应用、回调及权限后分别联调；本地测试使用模拟平台响应，不能证明实际应用权限审核或真实连接已完成。
