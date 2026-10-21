from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 素材对象存储。默认仅写入项目内的本地开发目录；云后端只暴露配置契约，
    # 本仓库不携带云凭证，也不会在未配置时尝试连接外部服务。
    material_storage_backend: str = "local"
    material_storage_local_root: str = ".local/material-storage"
    material_storage_max_bytes: int = 5 * 1024 * 1024 * 1024
    material_upload_session_ttl_seconds: int = 3600
    material_upload_part_size_bytes: int = 8 * 1024 * 1024
    material_storage_endpoint: str = ""
    material_storage_region: str = ""
    material_storage_bucket: str = ""
    material_storage_access_key_id: str = ""
    material_storage_access_key_secret: str = ""
    material_storage_path_style: bool = False
    tiktok_app_id: str = ""
    tiktok_app_secret: str = ""
    tiktok_access_token: str = ""
    tiktok_advertiser_id: str = ""
    # Business Center ID（可选）：配置后 /api/advertisers/ 会额外拉 BC 下全部子账户并 union
    tiktok_bc_id: str = ""
    tiktok_api_base_url: str = "https://business-api.tiktok.com/open_api/v1.3"

    # 旧配置（保留兼容，作为 PRD 默认值）
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""

    # 产研库 PRD（只读）
    prd_mysql_host: str = ""
    prd_mysql_port: int = 3306
    prd_mysql_user: str = ""
    prd_mysql_password: str = ""
    prd_mysql_database: str = ""

    # 应用库 APP（读写）
    app_mysql_host: str = ""
    app_mysql_port: int = 3306
    app_mysql_user: str = ""
    app_mysql_password: str = ""
    app_mysql_database: str = ""

    # 业务库 BIZ（读写，第二阶段）
    biz_mysql_host: str = ""
    biz_mysql_port: int = 3306
    biz_mysql_user: str = ""
    biz_mysql_password: str = ""
    biz_mysql_database: str = ""

    # 订单库 ORDER（只读，业务订单原始表 = 运营面板付费侧真值源）
    # 用于把付费侧从 MaxCompute (T+1) 直连到业务库（实时 + 真值）
    order_mysql_host: str = ""
    order_mysql_port: int = 3306
    order_mysql_user: str = ""
    order_mysql_password: str = ""
    order_mysql_database: str = ""

    # 归因数仓 MaxCompute（用于拉取 metis_dw.ads_ad_delivery_di 等 ADS 层）
    odps_access_key_id: str = ""
    odps_access_key_secret: str = ""
    odps_endpoint: str = "https://service.us-west-1.maxcompute.aliyun.com/api"
    odps_project: str = "metis_dw"
    odps_tunnel_endpoint: str = ""  # 可选；不填使用默认

    # 阿里云 DMS Enterprise OpenAPI（用于 ClickHouse 实时同步 + MaxCompute 回退查询）
    # 鉴权复用 odps_access_key_id / odps_access_key_secret（同一 RAM 用户）
    # 也可独立指定 dms_access_key_id / dms_access_key_secret 覆盖
    dms_access_key_id: str = ""
    dms_access_key_secret: str = ""
    dms_endpoint: str = "dms-enterprise.us-west-1.aliyuncs.com"
    dms_ck_db_id: int = 79572320       # metis (ClickHouse)
    dms_mc_db_id: int = 80154230       # metis_dw (MaxCompute)
    dms_max_retries: int = 3
    dms_retry_backoff_sec: float = 1.5
    # 30min 自动同步任务总开关（默认 disabled，环境变量 ENABLE_CK_INTRADAY_SYNC=1 开启）
    enable_ck_intraday_sync: bool = False

    # 归因数据接入 11 视图：默认数据源（auto 模式下生效）
    # 取值：blend / attribution / legacy
    #   blend       — normalized 投放指标 + attribution 真值业务结果（推荐生产口径，默认）
    #   attribution — 纯归因表（biz_attribution_ad_daily/intraday，TikTok spend 当前不全）
    #   legacy      — 纯 normalized 表（旧口径，spend 完整但 revenue 失真）
    # 前端 ?source=blend|attribution|legacy 可强制指定，不传则按 auto 取这里的默认值
    data_source_default: str = "blend"

    # 兼容旧 env：仅当 data_source_default 未显式设置时才考虑 attribution_primary
    # （True → attribution，False → legacy；不影响 blend）
    attribution_primary: bool = False

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_api_base_url: str = "https://graph.facebook.com/v21.0"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    cors_origins: str = "*"

    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # 阶段 2：凭证加密 + OAuth 集成
    # ─────────────────────────────────────────────────────────
    # AES-256-GCM 主密钥（32 字节 base64）。生成：
    #   python -c "from core.crypto import generate_key_b64; print(generate_key_b64())"
    # 生产环境应通过 KMS / Vault 注入。
    encryption_key_b64: str = ""
    # OAuth 回调域名前缀（含协议），客户端授权后跳转回 ${base}/api/integrations/{platform}/oauth/callback
    oauth_redirect_base_url: str = "http://localhost:8000"
    # OAuth state HMAC 用密钥；默认复用 jwt_secret_key
    oauth_state_secret: str = ""
    oauth_state_ttl_sec: int = 600  # 10 分钟

    # 阶段 7 P0：邮件 + 限流 + 公网地址
    # ─────────────────────────────────────────────────────────
    # 邮件后端：console | smtp | disabled（默认 console，开发用日志退货）
    email_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_sec: int = 15
    email_from: str = "no-reply@adsmind.local"
    email_from_name: str = "AdsMind"

    # 公网访问 base URL（带 scheme，无尾斜杠）。
    # 用于邮件里的验证 / 邀请链接，缺省回退到 request.origin / host。
    public_base_url: str = ""

    # 速率限制（per-IP，使用进程内 token bucket，无外部依赖）
    rate_limit_enabled: bool = True
    # 单 IP 注册：每小时上限
    rate_limit_register_per_hour: int = 20
    # 单 IP 登录：每分钟上限（防爆破）
    rate_limit_login_per_minute: int = 10
    # 单 IP 重发验证邮件 / 创建邀请：每小时上限
    rate_limit_email_per_hour: int = 30

    # 运行环境标识：production / staging / development（生产硬检查 ENCRYPTION_KEY_B64 / JWT_SECRET_KEY）
    app_env: str = ""

    # 允许 .env 出现未在 Settings 显式声明的字段（容忍未来扩展，避免启动崩溃）
    model_config = {
        "env_file": "../.env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
