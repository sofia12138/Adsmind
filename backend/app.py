"""AdsMind — 广告投放管理系统 FastAPI 入口"""

import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from config import get_settings
from db import DatabaseUnavailableError, validate_db_config
from tiktok_ads.api.client import TikTokApiError
from meta_ads.api.client import MetaApiError

# ── 定时同步任务 ───────────────────────────────────────────
#
# 两个错开的调度任务：
#   Job 1  sync_all_job    — 全量同步（结构 + 日报 + 回传），每 20 分钟，启动后 20 分钟首次执行
#   Job 2  sync_reports_job — 仅日报 + 回传（不含结构），每 20 分钟，启动后 30 分钟首次执行（错开 10 分钟）
#
# 之所以错开而非合并：避免同时向平台 API 发起大量请求，降低触发限流风险。

_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def _sync_all_job():
    """Job 1：全量同步（Campaign/Adset/Ad 结构 + 所有层级日报 + 回传转化）"""
    from tasks.sync_campaigns import run as sync_run

    end   = date.today()
    start = end - timedelta(days=1)
    date_range = f"{start} ~ {end}"
    logger.info(f"全量同步开始: {date_range}")
    try:
        await sync_run(start_date=str(start), end_date=str(end))
        logger.info(f"全量同步完成: {date_range}")
    except Exception as e:
        # run() owns per-application state; a failure before scope enumeration
        # cannot be assigned to an arbitrary tenant/application.
        logger.error(f"全量同步失败: {e}")

    # 全量同步完成后，附带同步优化师映射和事实表
    # 阶段 3 批次 1：路径迁至 plugins.optimizer.sync_job（原 tasks.sync_optimizer 保留 shim）
    try:
        from plugins.optimizer.sync_job import run as sync_optimizer_run
        opt_start = end - timedelta(days=7)
        sync_optimizer_run(str(opt_start), str(end))
        logger.info("优化师映射同步完成")
    except Exception as e:
        logger.error(f"优化师映射同步失败: {e}")

    # 附带同步剧级映射和事实表（fact_drama_daily）
    # 复用近 7 天的窗口，覆盖回传归因可能的滞后写入
    # 阶段 3 批次 1：路径迁至 plugins.drama.sync_job（原 tasks.sync_drama 保留 shim）
    try:
        from plugins.drama.sync_job import run as sync_drama_run
        drama_start = end - timedelta(days=7)
        sync_drama_run(str(drama_start), str(end))
        logger.info("剧级映射/事实表同步完成")
    except Exception as e:
        logger.error(f"剧级映射/事实表同步失败: {e}")


async def _sync_reports_job():
    """Job 2：仅同步日报 + 回传（错开 10 分钟，弥补高频数据实时性）"""
    from tasks.sync_campaigns import run as sync_run

    end   = date.today()
    start = end  # 仅今天
    date_range = f"{start}"
    logger.info(f"日报补充同步开始: {date_range}")
    # 通过 platform=None 触发所有平台今天的日报同步
    # run() 内部会同时更新 sync_state
    try:
        await sync_run(start_date=str(start), end_date=str(end))
        logger.info(f"日报补充同步完成: {date_range}")
    except Exception as e:
        logger.error(f"日报补充同步失败: {e}")


async def _sync_attribution_job():
    """Job 3：归因日报 T+1 cohort 同步（DMS OpenAPI 拉 metis_dw.ads_ad_delivery_di 121 天）

    每天跑一次，建议在 LA 上午 10 点之后（上游 T+1 已出）。
    """
    import asyncio
    settings = get_settings()
    if not (settings.dms_access_key_id or settings.odps_access_key_id):
        logger.info("归因同步：缺少 AccessKey（DMS_/ODPS_*），跳过本次")
        return

    from tasks.sync_attribution_daily import run as sync_attr_run
    logger.info("归因日报同步开始（默认 121 天回刷窗口）")
    try:
        result = await asyncio.to_thread(sync_attr_run)
        logger.info(f"归因日报同步完成: {result}")
    except Exception as e:
        logger.error(f"归因日报同步失败: {e}")


async def _sync_ops_daily_job():
    """Job 5：运营数据日报同步（每天 1 次，默认回填最近 30 天）

    数据流：metis_dw.{ads_app_di, dwd_recharge_order_df} (MaxCompute, via DMS)
        → adpilot_biz.biz_ops_daily

    覆盖运营面板所有指标：注册 / 激活 / DAU / 留存 / 双端订阅+内购充值 / 付费 UV
    """
    import asyncio
    settings = get_settings()
    if not (settings.dms_access_key_id or settings.odps_access_key_id):
        logger.info("运营数据同步：缺少 AccessKey（DMS_/ODPS_*），跳过本次")
        return

    from tasks.sync_ops_daily import run as sync_ops_run
    logger.info("运营数据日报同步开始（默认 30 天回刷窗口）")
    try:
        result = await asyncio.to_thread(sync_ops_run)
        logger.info(f"运营数据日报同步完成: {result}")
    except Exception as e:
        logger.error(f"运营数据日报同步失败: {e}")


async def _sync_ops_pay_intraday_job():
    """Job 6：运营面板付费侧高频同步 (每 30 分钟，默认窗口=今天+昨天 LA)

    数据流：metis_dw.dwd_recharge_order_df → biz_ops_daily (os_type=1/2 行)
    口径与 sync_ops_daily 付费侧完全一致；本任务只为压低收入展示时延。
    user 侧 (ads_app_di) + spend 仍由 sync_ops_daily 主任务处理。
    """
    import asyncio
    settings = get_settings()
    if not (settings.dms_access_key_id or settings.odps_access_key_id):
        logger.info("运营付费侧高频同步：缺少 AccessKey（DMS_/ODPS_*），跳过本次")
        return

    from tasks.sync_ops_pay_intraday import run as sync_ops_pay_run
    logger.info("运营付费侧高频同步开始（默认窗口=今天+昨天 LA）")
    try:
        result = await asyncio.to_thread(sync_ops_pay_run)
        logger.info(f"运营付费侧高频同步完成: {result}")
    except Exception as e:
        logger.error(f"运营付费侧高频同步失败: {e}")


async def _sync_ops_polardb_daily_job():
    """Job 7：运营面板付费侧 PolarDB T+1 同步（每 2 小时，默认 30 天回填）

    数据流：matrix_order.recharge_order (PolarDB) → biz_ops_daily_polardb_shadow

    与 Job 5 (sync_ops_daily 走 MaxCompute dwd) 双轨并行，影子表用于对账。
    无 AccessKey 依赖，但需要 ORDER_MYSQL_* 已配置且服务器在 PolarDB 白名单内。
    """
    import asyncio
    settings = get_settings()
    if not settings.order_mysql_database:
        logger.info("PolarDB 运营日报同步：ORDER_MYSQL_DATABASE 未配置，跳过本次")
        return

    from tasks.sync_ops_polardb_daily import run as sync_run
    logger.info("PolarDB 运营日报同步开始（默认 30 天回刷窗口）")
    try:
        result = await asyncio.to_thread(sync_run)
        logger.info(f"PolarDB 运营日报同步完成: {result}")
    except Exception as e:
        logger.error(f"PolarDB 运营日报同步失败: {e}")


async def _sync_ops_polardb_intraday_job():
    """Job 8：运营面板付费侧 PolarDB 实时同步（每 10 分钟，今日+昨日 LA）

    数据流：matrix_order.recharge_order (PolarDB) → biz_ops_daily_intraday
    口径与 Job 7 完全一致，仅窗口和目标表不同。

    频率说明：聚合的 recharge_order 数据量很小（~1300 行），单次查询 200ms 内，
    比 dwd 主路径轻 10 倍以上，可以高频跑而不增加显著负载。
    """
    import asyncio
    settings = get_settings()
    if not settings.order_mysql_database:
        logger.info("PolarDB 运营实时同步：ORDER_MYSQL_DATABASE 未配置，跳过本次")
        return

    from tasks.sync_ops_polardb_intraday import run as sync_run
    logger.info("PolarDB 运营实时同步开始（窗口=今天+昨天 LA）")
    try:
        result = await asyncio.to_thread(sync_run)
        logger.info(f"PolarDB 运营实时同步完成: {result}")
    except Exception as e:
        logger.error(f"PolarDB 运营实时同步失败: {e}")


async def _oauth_credential_alert_job():
    """阶段 7 P0：每日扫描即将过期 / 已过期的 OAuth 凭证并通知租户管理员。"""
    import asyncio
    try:
        from tasks.oauth_credential_alerts import run as _run_alerts
        result = await asyncio.to_thread(_run_alerts)
        logger.info(f"OAuth 凭证过期扫描完成: {result}")
    except Exception as e:
        logger.warning(f"OAuth 凭证过期扫描失败: {e}")


async def _sync_attribution_intraday_job():
    """Job 4：CK D0 实时归因同步 (默认窗口=今天+昨天 LA)

    每 30 分钟一次，从 metis ClickHouse (dwd_*_rt) 拉 D0 实时数据 → BIZ MySQL
    biz_attribution_ad_intraday。前端通过双源拼接拿到 T+1 cohort + D0 实时。
    """
    import asyncio
    settings = get_settings()
    if not settings.enable_ck_intraday_sync:
        return  # 默认关闭，环境变量 ENABLE_CK_INTRADAY_SYNC=true 开启
    if not (settings.dms_access_key_id or settings.odps_access_key_id):
        logger.info("CK 实时同步：缺少 AccessKey，跳过本次")
        return

    from tasks.sync_attribution_intraday import run as sync_intraday_run
    logger.info("CK D0 实时同步开始（默认窗口=今天+昨天 LA）")
    try:
        result = await asyncio.to_thread(sync_intraday_run)
        logger.info(f"CK D0 实时同步完成: {result}")
    except Exception as e:
        logger.error(f"CK D0 实时同步失败: {e}")


# ── 生命周期：只读校验 + 启动调度器 ──────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    validate_db_config()
    from migrations.schema_guard import assert_release_schema_ready
    assert_release_schema_ready()

    # 阶段 2：加密链路自检
    # ────────────────────────────────────────────────────────
    # 环境识别：
    #   - APP_ENV=production / prod                  → 必须配置 ENCRYPTION_KEY_B64
    #                                                  否则启动失败（防止生产用临时密钥）
    #   - jwt_secret_key 仍是默认 'change-me-in-production' → 视为开发环境，允许临时密钥
    #   - 其余                                       → 允许临时密钥但 WARN
    try:
        import os as _os
        from core import crypto
        env_name = (_os.getenv("APP_ENV", "") or "").strip().lower()
        is_prod = env_name in ("production", "prod")
        if not crypto.is_configured():
            if is_prod:
                logger.error(
                    "❌ 生产环境（APP_ENV={}）未配置 ENCRYPTION_KEY_B64，启动中止。"
                    " 请运行：python -c \"from core.crypto import generate_key_b64; print(generate_key_b64())\""
                    " 然后写入环境变量再重启。".format(env_name)
                )
                raise RuntimeError(
                    "ENCRYPTION_KEY_B64 must be configured in production"
                )
            _ephemeral = crypto.generate_key_b64()
            _os.environ["ENCRYPTION_KEY_B64"] = _ephemeral
            crypto._load_keyring.cache_clear()
            logger.warning(
                "⚠ 未配置 ENCRYPTION_KEY_B64，已为本进程生成临时密钥（重启后 OAuth 密文需重新授权）。"
                " 生产环境请显式设置 APP_ENV=production 并写入持久化密钥。"
            )
        if crypto.is_configured():
            if crypto.selftest():
                logger.info("加密自检通过（AES-256-GCM）")
            else:
                logger.error("⚠ 加密自检失败！请检查 ENCRYPTION_KEY_B64 是否正确")
                if is_prod:
                    raise RuntimeError("crypto selftest failed in production")

        # JWT secret 弱密钥提醒（生产强制报错）
        try:
            jwt_secret = getattr(get_settings(), "jwt_secret_key", "") or ""
        except Exception:
            jwt_secret = ""
        if jwt_secret in ("", "change-me-in-production"):
            if is_prod:
                logger.error(
                    "❌ 生产环境 jwt_secret_key 仍为默认值，启动中止。"
                    " 请在环境变量中设置 JWT_SECRET_KEY=<随机 32+ 位字符串>"
                )
                raise RuntimeError("jwt_secret_key must be customized in production")
            logger.warning(
                "⚠ jwt_secret_key 仍是默认 'change-me-in-production'，请勿用于生产。"
            )
    except RuntimeError:
        # 重新抛出，阻止启动
        raise
    except Exception as e:
        logger.warning(f"加密模块加载失败：{e}")

    # 阶段 3 批次 1：插件 jobs/hooks 注册（本批次插件暂未声明 jobs，
    # 但接入接口便于批次 2 attribution_metis / ops_panel、批次 3 returned_conversion 复用）
    try:
        from core import plugin_loader
        plugin_jobs_summary = plugin_loader.register_jobs_and_hooks(_scheduler, get_settings())
        logger.info(f"插件 jobs/hooks 注册完成: {plugin_jobs_summary}")
    except Exception as e:
        logger.warning(f"插件 jobs/hooks 注册失败（不影响启动）：{e}")

    now = datetime.now()

    # Job 1：全量同步（每 20 分钟，启动后 20 分钟首次）
    _scheduler.add_job(
        _sync_all_job,
        trigger="interval",
        minutes=20,
        id="sync_all",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=20),
    )

    # Job 2：日报补充同步（每 20 分钟，启动后 30 分钟首次，与 Job1 错开 10 分钟）
    _scheduler.add_job(
        _sync_reports_job,
        trigger="interval",
        minutes=20,
        id="sync_reports",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=30),
    )

    # Job 3：归因日报同步（每天 1 次，触发时 = LA 上午 10:30 = UTC+8 凌晨 02:30）
    # 上游 ads_ad_delivery_di 每日 INSERT OVERWRITE 121 个 LA cohort 分区
    _scheduler.add_job(
        _sync_attribution_job,
        trigger="cron",
        hour=2, minute=30,  # Asia/Shanghai 凌晨 02:30 ≈ LA 上午 10:30 / 11:30（看夏令时）
        id="sync_attribution",
        replace_existing=True,
    )

    # Job 5：运营数据日报同步（每 2 小时跑一次，user 侧 + 付费侧 + spend 全量回填）
    # 拉 metis_dw.{ads_app_di, dwd_recharge_order_df} → biz_ops_daily
    # 注：付费侧的实时刷新已交给 Job 6（每 30min），本任务保证 user 侧 / 历史窗口的全量准确性。
    _scheduler.add_job(
        _sync_ops_daily_job,
        trigger="interval",
        hours=2,
        id="sync_ops_daily",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=2),
    )

    # Job 6：运营面板付费侧高频同步（每 30 分钟，仅刷今天+昨天 LA 的付费侧）
    # 拉 metis_dw.dwd_recharge_order_df → biz_ops_daily (os_type=1/2)
    _scheduler.add_job(
        _sync_ops_pay_intraday_job,
        trigger="interval",
        minutes=30,
        id="sync_ops_pay_intraday",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=10),
    )

    # Job 7：运营面板付费侧 PolarDB T+1 同步（每 2 小时，30 天回填 → 影子表）
    # 拉 matrix_order.recharge_order → biz_ops_daily_polardb_shadow
    # 双轨对账期专用，与 Job 5 的 dwd 路径并行
    _scheduler.add_job(
        _sync_ops_polardb_daily_job,
        trigger="interval",
        hours=2,
        id="sync_ops_polardb_daily",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=4),  # 错开 Job 5 (minutes=2)
    )

    # Job 8：运营面板付费侧 PolarDB 实时同步（每 10 分钟，今日+昨日 LA → 实时层）
    # 拉 matrix_order.recharge_order → biz_ops_daily_intraday
    # API 智能路由（routes/ops.py）：今日/昨日 → 这张表；历史 → biz_ops_daily
    # 频率：10 分钟（聚合 ~1300 行，单次 ~200ms，可以高频跑）
    _scheduler.add_job(
        _sync_ops_polardb_intraday_job,
        trigger="interval",
        minutes=10,
        id="sync_ops_polardb_intraday",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=2),  # 启动后 2 分钟立刻跑首次
    )

    # Job 9：OAuth 凭证过期扫描（每天一次）
    _scheduler.add_job(
        _oauth_credential_alert_job,
        trigger="cron",
        hour=3,
        minute=20,
        id="oauth_credential_alerts",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=8),  # 启动后 8 分钟跑一次首扫
    )

    # Job 4：CK D0 实时归因同步（默认 disabled；ENABLE_CK_INTRADAY_SYNC=true 开启）
    # 启用后每 30 分钟拉 metis.dwd_*_rt 当天 + 昨天 LA 数据，覆盖到 biz_attribution_ad_intraday
    _settings = get_settings()
    if _settings.enable_ck_intraday_sync:
        _scheduler.add_job(
            _sync_attribution_intraday_job,
            trigger="interval",
            minutes=30,
            id="sync_attribution_intraday",
            replace_existing=True,
            next_run_time=now + timedelta(minutes=5),
        )
        logger.info(
            "定时同步调度器已启动（全量每 20 分钟 | 日报错开 10 分钟 | "
            "归因每日 02:30 | 运营每 2 小时 | 运营付费侧每 30 分钟 | "
            "PolarDB 运营 T+1 每 2 小时 | PolarDB 运营实时每 10 分钟 | CK 实时每 30 分钟）"
        )
    else:
        logger.info(
            "定时同步调度器已启动（全量每 20 分钟 | 日报错开 10 分钟 | "
            "归因每日 02:30 | 运营每 2 小时 | 运营付费侧每 30 分钟 | "
            "PolarDB 运营 T+1 每 2 小时 | PolarDB 运营实时每 10 分钟）"
            "—— CK 实时同步未启用 (ENABLE_CK_INTRADAY_SYNC=false)"
        )

    _scheduler.start()

    logger.info("应用启动完成")
    yield

    _scheduler.shutdown(wait=False)
    logger.info("定时同步调度器已停止")


# ── 应用实例 ──────────────────────────────────────────────

app = FastAPI(
    title="AdsMind - 广告投放管理系统",
    description="对接 TikTok & Meta Marketing API，支持广告系列/广告组/广告的创建、管理和数据报表",
    version="1.0.0",
    lifespan=lifespan,
)


# ── 中间件 ────────────────────────────────────────────────

def _setup_middleware(application: FastAPI):
    settings = get_settings()
    origins = getattr(settings, "cors_origins", None) or ["*"]
    if isinstance(origins, str):
        origins = [o.strip() for o in origins.split(",")]
    from core.isolation import IsolationMiddleware

    # Only IsolationMiddleware may attach trusted tenant/application state.  The
    # former hint middlewares decoded JWTs without verification and could silently
    # fall back to another application, so they are intentionally not registered.
    application.add_middleware(IsolationMiddleware)
    # Starlette applies middleware in reverse registration order.  Keep CORS
    # outermost so authentication failures also receive the required headers.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


_setup_middleware(app)


# ── 路由注册 ──────────────────────────────────────────────

def _register_routers(application: FastAPI):
    from routes.auth import router as auth_router
    from routes.users import router as users_router
    from routes.campaigns import router as campaign_router
    from routes.adgroups import router as adgroup_router
    from routes.ads import router as ad_router
    from routes.reports import router as report_router
    from routes.creatives import router as creative_router
    from routes.advertisers import router as advertiser_router
    from routes.meta_accounts import router as meta_account_router
    from routes.meta_campaigns import router as meta_campaign_router
    from routes.meta_adsets import router as meta_adset_router
    from routes.meta_ads import router as meta_ad_router
    from routes.meta_reports import router as meta_report_router
    from routes.bizdata import router as bizdata_router
    from routes.oplog import router as oplog_router
    from routes.templates import router as template_router
    from routes.biz import router as biz_router
    from routes.panels import router as panels_router
    from routes.insight import router as insight_router
    from routes.accounts import router as accounts_router
    from routes.analysis import router as analysis_router
    from routes.sync import router as sync_router
    from routes.meta_assets import router as meta_assets_router
    from routes.ad_assets import router as ad_assets_router
    from routes.tiktok_materials import router as tiktok_materials_router
    from routes.attribution import router as attribution_router
    from routes.ops import router as ops_router
    from routes.integrations import router as integrations_router
    from routes.applications import router as applications_router
    from routes.registration import router as registration_router
    from routes.quota import router as quota_router
    from routes.billing import router as billing_router
    from routes.invitations import (
        tenant_router as invitations_tenant_router,
        public_router as invitations_public_router,
    )

    from routes.launch_drafts import router as launch_drafts_router
    from routes.distribution import router as distribution_router
    from drama_catalog.routes import router as drama_catalog_router
    from material_catalog.routes import router as material_catalog_router
    from creative_groups.routes import router as creative_groups_router
    from ad_creation.routes import router as ad_creation_router
    from platform_preflight.routes import router as platform_preflight_router
    from routes.application_settings import router as application_settings_router
    for r in [
        drama_catalog_router,
        material_catalog_router,
        creative_groups_router,
        ad_creation_router,
        platform_preflight_router,
        application_settings_router,
        distribution_router,
        launch_drafts_router,
        registration_router,
        invitations_public_router,  # 挂在 /auth 前缀下，匿名可访问
        invitations_tenant_router,  # 挂在 /tenant 前缀下，需要 admin
        quota_router,
        billing_router,
        auth_router, users_router, campaign_router, adgroup_router,
        ad_router, report_router, creative_router, advertiser_router,
        meta_account_router, meta_campaign_router, meta_adset_router,
        meta_ad_router, meta_report_router, bizdata_router, oplog_router,
        template_router, biz_router, panels_router, insight_router,
        accounts_router, analysis_router, sync_router,
        meta_assets_router, ad_assets_router,
        tiktok_materials_router, attribution_router, ops_router,
        integrations_router, applications_router,
    ]:
        application.include_router(r, prefix="/api")

    # 阶段 3 批次 1：drama / optimizer / designer_performance 改由插件自行注册
    # 路由 prefix 不变（仍是 /api/...），仅注册路径从 routes.* 迁至 plugins.*.routes
    from core import plugin_loader
    plugin_summary = plugin_loader.register_routes(application)
    logger.info(f"插件路由注册完成: {plugin_summary}")


_register_routers(app)


# ── 静态文件 ──────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── 异常处理 ──────────────────────────────────────────────

@app.exception_handler(TikTokApiError)
async def tiktok_api_error_handler(request: Request, exc: TikTokApiError):
    logger.error(f"TikTok API 错误: {exc}")
    return JSONResponse(
        status_code=400,
        content={
            "error": "tiktok_api_error",
            "code": exc.code,
            "message": exc.message,
            "request_id": exc.request_id,
        },
    )


@app.exception_handler(MetaApiError)
async def meta_api_error_handler(request: Request, exc: MetaApiError):
    logger.error(f"Meta API 错误: {exc}")
    return JSONResponse(
        status_code=400,
        content={
            "error": "meta_api_error",
            "code": exc.code,
            "message": exc.message,
            "fbtrace_id": exc.fbtrace_id,
        },
    )


@app.exception_handler(DatabaseUnavailableError)
async def db_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
    logger.error(f"数据库不可用: {exc}")
    return JSONResponse(
        status_code=503,
        content={"error": "database_unavailable", "message": "数据库连接不可用，请稍后重试"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"参数错误: {exc}")
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": str(exc)},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    logger.warning(f"权限不足: {exc}")
    return JSONResponse(
        status_code=403,
        content={"error": "forbidden", "message": str(exc) or "权限不足"},
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    logger.warning(f"资源未找到: {exc}")
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "message": f"资源未找到: {exc}"},
    )


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.exception(f"未捕获异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "服务器内部错误"},
    )


# ── 基础端点 ──────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "AdsMind API is running"}


@app.get("/health", tags=["系统"])
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "tiktok_configured": bool(settings.tiktok_access_token),
        "meta_configured": bool(settings.meta_access_token),
        "tiktok_advertiser_id": settings.tiktok_advertiser_id,
        "meta_ad_account_id": settings.meta_ad_account_id,
    }


# ── SPA fallback ──────────────────────────────────────────
# React Router 的前端路由（/login, /dashboard 等）直接访问或刷新时，
# 后端找不到对应处理器，必须 fallback 到 index.html 由前端接管。
# 注意：必须最后注册，以避免拦截已声明的 API/静态路径。
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "static/", "docs", "redoc", "openapi.json")):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


# ── 开发入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
    )
