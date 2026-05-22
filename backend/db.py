# -*- coding: utf-8 -*-
"""三库隔离数据库层 — PRD(产研/只读) / APP(应用/读写) / BIZ(业务/读写)"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pymysql
import pymysql.cursors
from loguru import logger

from config import get_settings


class DatabaseUnavailableError(Exception):
    """MySQL 连接不可用时抛出，由全局异常处理器捕获返回 503"""
    pass


# ═══════════════════════════════════════════════════════════
#  三库连接池（完全隔离）
# ═══════════════════════════════════════════════════════════

_POOL_SIZE = 5

_prd_pool: list[pymysql.Connection] = []
_app_pool: list[pymysql.Connection] = []
_biz_pool: list[pymysql.Connection] = []
_order_pool: list[pymysql.Connection] = []

_prd_available: bool | None = None
_order_available: bool | None = None


# ── 安全校验 ──────────────────────────────────────────────

def validate_db_config():
    """启动时调用，校验三库配置不冲突。"""
    settings = get_settings()
    prd_db = _resolve_prd_database(settings)

    app_db = settings.app_mysql_database
    if not app_db:
        raise RuntimeError("APP_MYSQL_DATABASE 未配置，请设置应用库数据库名")
    if app_db == prd_db:
        raise RuntimeError(
            f"APP_MYSQL_DATABASE('{app_db}') 不能指向产研库 '{prd_db}'，请配置独立数据库"
        )

    biz_db = settings.biz_mysql_database
    if biz_db:
        if biz_db == prd_db:
            raise RuntimeError(
                f"BIZ_MYSQL_DATABASE('{biz_db}') 不能指向产研库 '{prd_db}'，请配置独立数据库"
            )
        if biz_db == app_db:
            raise RuntimeError(
                f"BIZ_MYSQL_DATABASE('{biz_db}') 不能与 APP_MYSQL_DATABASE('{app_db}') 相同"
            )

    logger.info(f"数据库配置校验通过: PRD={prd_db}, APP={app_db}, BIZ={biz_db or '(未配置)'}")


def _resolve_prd_database(settings) -> str:
    return settings.prd_mysql_database or settings.mysql_database


# ── 连接创建 ──────────────────────────────────────────────

def _create_prd_conn() -> pymysql.Connection:
    """创建产研库连接（只读）"""
    settings = get_settings()
    return pymysql.connect(
        host=settings.prd_mysql_host or settings.mysql_host,
        port=settings.prd_mysql_port or settings.mysql_port,
        user=settings.prd_mysql_user or settings.mysql_user,
        password=settings.prd_mysql_password or settings.mysql_password,
        database=settings.prd_mysql_database or settings.mysql_database,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _create_app_conn() -> pymysql.Connection:
    """创建应用库连接（读写）"""
    settings = get_settings()
    return pymysql.connect(
        host=settings.app_mysql_host or settings.mysql_host,
        port=settings.app_mysql_port or settings.mysql_port,
        user=settings.app_mysql_user or settings.mysql_user,
        password=settings.app_mysql_password or settings.mysql_password,
        database=settings.app_mysql_database,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _create_biz_conn() -> pymysql.Connection:
    """创建业务库连接（读写，第二阶段）"""
    settings = get_settings()
    if not settings.biz_mysql_database:
        raise DatabaseUnavailableError("BIZ_MYSQL_DATABASE 未配置")
    return pymysql.connect(
        host=settings.biz_mysql_host or settings.mysql_host,
        port=settings.biz_mysql_port or settings.mysql_port,
        user=settings.biz_mysql_user or settings.mysql_user,
        password=settings.biz_mysql_password or settings.mysql_password,
        database=settings.biz_mysql_database,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _create_order_conn() -> pymysql.Connection:
    """创建订单库连接（只读，PolarDB 业务原始订单表 matrix_order.*）"""
    settings = get_settings()
    if not settings.order_mysql_database:
        raise DatabaseUnavailableError("ORDER_MYSQL_DATABASE 未配置")
    return pymysql.connect(
        host=settings.order_mysql_host,
        port=settings.order_mysql_port or 3306,
        user=settings.order_mysql_user,
        password=settings.order_mysql_password,
        database=settings.order_mysql_database,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=30,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


# ── 连接池管理（通用） ────────────────────────────────────

def _acquire(pool: list[pymysql.Connection],
             create_fn, label: str) -> pymysql.Connection | None:
    """从池中获取可用连接或新建。返回连接或 None。"""
    while pool:
        c = pool.pop()
        try:
            c.ping(reconnect=True)
            return c
        except Exception:
            try:
                c.close()
            except Exception:
                pass
    return create_fn()


def _release(pool: list[pymysql.Connection], conn: pymysql.Connection):
    """归还连接到池中"""
    if len(pool) < _POOL_SIZE:
        try:
            pool.append(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    else:
        try:
            conn.close()
        except Exception:
            pass


# ── 上下文管理器 ──────────────────────────────────────────

@contextmanager
def get_prd_conn():
    """产研库连接（只读）。连接失败 → yield None（兼容旧 bizdata 降级）。"""
    global _prd_available
    try:
        conn = _acquire(_prd_pool, _create_prd_conn, "PRD")
    except Exception as e:
        if _prd_available is not False:
            logger.warning(f"PRD 产研库连接失败（已静默跳过）: {e}")
            _prd_available = False
        yield None
        return
    _prd_available = True
    try:
        yield conn
    finally:
        _release(_prd_pool, conn)


@contextmanager
def get_app_conn():
    """应用库连接（读写）。连接失败 → 抛出 DatabaseUnavailableError。"""
    try:
        conn = _acquire(_app_pool, _create_app_conn, "APP")
    except Exception as e:
        raise DatabaseUnavailableError(f"APP 应用库连接失败: {e}") from e
    try:
        yield conn
    finally:
        _release(_app_pool, conn)


@contextmanager
def get_biz_conn():
    """业务库连接（读写，第二阶段）。连接失败 → 抛出 DatabaseUnavailableError。"""
    try:
        conn = _acquire(_biz_pool, _create_biz_conn, "BIZ")
    except Exception as e:
        raise DatabaseUnavailableError(f"BIZ 业务库连接失败: {e}") from e
    try:
        yield conn
    finally:
        _release(_biz_pool, conn)


@contextmanager
def get_order_conn():
    """订单库连接（只读，PolarDB matrix_order）。连接失败 → yield None。

    与 PRD 一致采用「静默降级」：上游业务库白名单/网络问题不应让运营面板整体崩溃，
    让上层自行决定是否回退到 dwd 兜底（参见 ops_service）。
    """
    global _order_available
    try:
        conn = _acquire(_order_pool, _create_order_conn, "ORDER")
    except Exception as e:
        if _order_available is not False:
            logger.warning(f"ORDER 订单库连接失败（已静默跳过）: {e}")
            _order_available = False
        yield None
        return
    _order_available = True
    try:
        yield conn
    finally:
        _release(_order_pool, conn)


# 兼容旧代码：get_conn = get_prd_conn
get_conn = get_prd_conn


# ═══════════════════════════════════════════════════════════
#  产研库查询函数（全部使用 get_prd_conn）
# ═══════════════════════════════════════════════════════════

_ca_map_cache: dict[int, str] = {}
_ca_map_ts: float = 0
_CA_MAP_TTL = 300


def get_channel_advertiser_map() -> dict[int, str]:
    global _ca_map_cache, _ca_map_ts
    now = time.time()
    if _ca_map_cache and (now - _ca_map_ts) < _CA_MAP_TTL:
        return _ca_map_cache

    sql = """
        SELECT DISTINCT c.channel_id, t.advertiser_id
        FROM channel_day_report c
        JOIN tiktok_media_campaign_day t ON c.campaign_id = t.campaign_id
        WHERE t.advertiser_id IS NOT NULL AND t.advertiser_id != ''
    """
    with get_prd_conn() as conn:
        if conn is None:
            return _ca_map_cache or {}
        cur = conn.cursor()
        cur.execute(sql)
        _ca_map_cache = {r["channel_id"]: r["advertiser_id"] for r in cur.fetchall()}
        _ca_map_ts = now
    return _ca_map_cache


def query_channel_report(
    start_date: str,
    end_date: str,
    campaign_id: Optional[str] = None,
    advertiser_id: Optional[str] = None,
    ad_platform: Optional[int] = None,
) -> list[dict]:
    sql = """
        SELECT
            c.campaign_id, c.report_date, c.channel_id,
            c.register_count, c.first_subscribe_count, c.first_subscribe_amount,
            c.repeat_subscribe_count, c.repeat_subscribe_amount,
            c.first_inapp_count, c.first_inapp_amount,
            c.repeat_inapp_count, c.repeat_inapp_amount,
            c.inapp_total_amount, c.subscribe_total_amount,
            c.recharge_total_amount, c.ad_cost_amount,
            c.day1_roi, c.day3_roi, c.day7_roi, c.day14_roi,
            c.day30_roi, c.day90_roi, c.day120_roi, c.ad_platform
        FROM channel_day_report c
        WHERE c.report_date BETWEEN %s AND %s
    """
    params: list = [start_date, end_date]

    if campaign_id:
        sql += " AND c.campaign_id = %s"
        params.append(campaign_id)
    if ad_platform is not None:
        sql += " AND c.ad_platform = %s"
        params.append(ad_platform)

    sql += " ORDER BY c.report_date DESC"

    with get_prd_conn() as conn:
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    if advertiser_id:
        mapping = get_channel_advertiser_map()
        rows = [r for r in rows if mapping.get(r["channel_id"]) == advertiser_id]

    return rows


def query_channel_report_summary(
    start_date: str,
    end_date: str,
    campaign_id: Optional[str] = None,
    advertiser_id: Optional[str] = None,
    ad_platform: Optional[int] = None,
) -> dict:
    rows = query_channel_report(start_date, end_date, campaign_id, advertiser_id, ad_platform)
    summary = {
        "register_count": 0, "first_subscribe_count": 0, "first_subscribe_amount": 0,
        "repeat_subscribe_count": 0, "repeat_subscribe_amount": 0,
        "first_inapp_count": 0, "first_inapp_amount": 0,
        "repeat_inapp_count": 0, "repeat_inapp_amount": 0,
        "inapp_total_amount": 0, "subscribe_total_amount": 0,
        "recharge_total_amount": 0, "ad_cost_amount": 0,
        "day1_roi": 0, "day3_roi": 0, "day7_roi": 0,
        "day14_roi": 0, "day30_roi": 0, "day90_roi": 0, "day120_roi": 0,
    }
    for r in rows:
        for k in summary:
            summary[k] += int(r.get(k, 0) or 0)

    if rows:
        roi_count = len([r for r in rows if r.get("day1_roi", 0)])
        if roi_count:
            for k in ["day1_roi", "day3_roi", "day7_roi", "day14_roi",
                       "day30_roi", "day90_roi", "day120_roi"]:
                summary[k] = round(summary[k] / roi_count)

    return summary


def query_campaign_business_map(
    start_date: str,
    end_date: str,
    ad_platform: Optional[int] = None,
) -> dict[str, dict]:
    rows = query_channel_report(start_date, end_date, ad_platform=ad_platform)
    result: dict[str, dict] = {}
    for r in rows:
        cid = str(r["campaign_id"])
        if not cid:
            continue
        if cid not in result:
            result[cid] = {
                "register_count": 0, "first_subscribe_count": 0,
                "subscribe_total_amount": 0, "inapp_total_amount": 0,
                "recharge_total_amount": 0, "purchase_count": 0,
                "day1_roi": 0, "day3_roi": 0, "day7_roi": 0,
                "day14_roi": 0, "day30_roi": 0, "day90_roi": 0, "day120_roi": 0,
                "_count": 0,
            }
        d = result[cid]
        d["register_count"] += int(r.get("register_count", 0) or 0)
        d["first_subscribe_count"] += int(r.get("first_subscribe_count", 0) or 0)
        d["subscribe_total_amount"] += int(r.get("subscribe_total_amount", 0) or 0)
        d["inapp_total_amount"] += int(r.get("inapp_total_amount", 0) or 0)
        d["recharge_total_amount"] += int(r.get("recharge_total_amount", 0) or 0)
        d["purchase_count"] += int(r.get("first_inapp_count", 0) or 0) + int(r.get("repeat_inapp_count", 0) or 0)
        for k in ["day1_roi", "day3_roi", "day7_roi", "day14_roi",
                   "day30_roi", "day90_roi", "day120_roi"]:
            d[k] += int(r.get(k, 0) or 0)
        d["_count"] += 1

    for cid, d in result.items():
        if d["_count"] > 0:
            for k in ["day1_roi", "day3_roi", "day7_roi", "day14_roi",
                       "day30_roi", "day90_roi", "day120_roi"]:
                d[k] = round(d[k] / d["_count"])
        del d["_count"]

    return result


def query_media_campaign_day(
    start_date: str,
    end_date: str,
    platform: str = "tiktok",
    advertiser_id: Optional[str] = None,
) -> list[dict]:
    if platform == "tiktok":
        sql = "SELECT * FROM tiktok_media_campaign_day WHERE stat_time_day BETWEEN %s AND %s"
        params: list = [start_date, end_date]
        if advertiser_id:
            sql += " AND advertiser_id = %s"
            params.append(advertiser_id)
    else:
        sql = "SELECT * FROM facebook_media_campaign_day WHERE stat_time_day BETWEEN %s AND %s"
        params = [start_date, end_date]
        if advertiser_id:
            sql += " AND account_id = %s"
            params.append(advertiser_id)

    sql += " ORDER BY stat_time_day DESC"

    with get_prd_conn() as conn:
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


# ═══════════════════════════════════════════════════════════
#  应用库建表 + 迁移（全部使用 _create_app_conn）
# ═══════════════════════════════════════════════════════════

_APP_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS panel_definitions (
        id          BIGINT AUTO_INCREMENT PRIMARY KEY,
        panel_key   VARCHAR(100) NOT NULL UNIQUE,
        panel_name  VARCHAR(200) NOT NULL DEFAULT '',
        panel_group VARCHAR(100) NOT NULL DEFAULT '',
        route_path  VARCHAR(200) NOT NULL DEFAULT '',
        sort_order  INT          NOT NULL DEFAULT 0,
        is_enabled  TINYINT      NOT NULL DEFAULT 1,
        created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_group (panel_group),
        INDEX idx_sort (sort_order)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS role_panel_permissions (
        id          BIGINT AUTO_INCREMENT PRIMARY KEY,
        role_key    VARCHAR(50)  NOT NULL,
        panel_key   VARCHAR(100) NOT NULL,
        can_view    TINYINT      NOT NULL DEFAULT 1,
        created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_role_panel (role_key, panel_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_panel_permissions (
        id          BIGINT AUTO_INCREMENT PRIMARY KEY,
        username    VARCHAR(100) NOT NULL,
        panel_key   VARCHAR(100) NOT NULL,
        can_view    TINYINT      NOT NULL DEFAULT 1,
        source_type VARCHAR(20)  NOT NULL DEFAULT 'user',
        created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_user_panel (username, panel_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_insight_config (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        config_key   VARCHAR(100) NOT NULL UNIQUE,
        config_value JSON         NOT NULL,
        created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_users (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        username        VARCHAR(100) NOT NULL UNIQUE,
        password_hash   VARCHAR(255) NOT NULL,
        role            VARCHAR(50)  NOT NULL DEFAULT 'optimizer',
        display_name    VARCHAR(100) NOT NULL DEFAULT '',
        assigned_accounts JSON       DEFAULT NULL,
        status          VARCHAR(20)  NOT NULL DEFAULT 'active',
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_role (role)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_templates (
        id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
        tpl_id             VARCHAR(64)  NOT NULL UNIQUE,
        template_key       VARCHAR(64)  DEFAULT NULL,
        name               VARCHAR(255) NOT NULL DEFAULT '',
        platform           VARCHAR(50)  NOT NULL DEFAULT 'tiktok',
        is_builtin         TINYINT      NOT NULL DEFAULT 0,
        is_system          TINYINT      NOT NULL DEFAULT 0,
        is_editable        TINYINT      NOT NULL DEFAULT 1,
        parent_template_id VARCHAR(64)  DEFAULT NULL,
        content            JSON         NOT NULL,
        created_by         VARCHAR(100) NOT NULL DEFAULT '',
        created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_platform (platform),
        INDEX idx_template_key (template_key),
        INDEX idx_is_system (is_system),
        INDEX idx_parent_tpl (parent_template_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_oplog (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id       BIGINT       DEFAULT NULL,
        username      VARCHAR(100) NOT NULL DEFAULT '',
        action        VARCHAR(100) NOT NULL DEFAULT '',
        target_type   VARCHAR(50)  NOT NULL DEFAULT '',
        target_id     VARCHAR(100) NOT NULL DEFAULT '',
        platform      VARCHAR(50)  NOT NULL DEFAULT '',
        before_data   JSON         DEFAULT NULL,
        after_data    JSON         DEFAULT NULL,
        status        VARCHAR(20)  NOT NULL DEFAULT 'success',
        error_message TEXT         DEFAULT NULL,
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_username (username),
        INDEX idx_target (target_type, target_id),
        INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # ── 广告资产库 ──
    """
    CREATE TABLE IF NOT EXISTS asset_landing_pages (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        org_id        VARCHAR(100) NOT NULL DEFAULT '',
        name          VARCHAR(255) NOT NULL DEFAULT '',
        landing_page_url TEXT NOT NULL,
        product_name  VARCHAR(255) NOT NULL DEFAULT '',
        channel       VARCHAR(100) NOT NULL DEFAULT '',
        language      VARCHAR(50)  NOT NULL DEFAULT '',
        region_tags   JSON         DEFAULT NULL,
        remark        TEXT         DEFAULT NULL,
        status        VARCHAR(20)  NOT NULL DEFAULT 'active',
        usage_count   INT          NOT NULL DEFAULT 0,
        last_used_at  DATETIME     DEFAULT NULL,
        created_by    VARCHAR(100) NOT NULL DEFAULT '',
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_org (org_id),
        INDEX idx_status (status),
        INDEX idx_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_copy_packs (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        org_id        VARCHAR(100) NOT NULL DEFAULT '',
        name          VARCHAR(255) NOT NULL DEFAULT '',
        primary_text  TEXT         DEFAULT NULL,
        headline      VARCHAR(500) NOT NULL DEFAULT '',
        description   TEXT         DEFAULT NULL,
        language      VARCHAR(50)  NOT NULL DEFAULT '',
        product_name  VARCHAR(255) NOT NULL DEFAULT '',
        channel       VARCHAR(100) NOT NULL DEFAULT '',
        country_tags  JSON         DEFAULT NULL,
        theme_tags    JSON         DEFAULT NULL,
        remark        TEXT         DEFAULT NULL,
        status        VARCHAR(20)  NOT NULL DEFAULT 'active',
        usage_count   INT          NOT NULL DEFAULT 0,
        last_used_at  DATETIME     DEFAULT NULL,
        created_by    VARCHAR(100) NOT NULL DEFAULT '',
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_org (org_id),
        INDEX idx_status (status),
        INDEX idx_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_region_groups (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        org_id        VARCHAR(100) NOT NULL DEFAULT '',
        name          VARCHAR(255) NOT NULL DEFAULT '',
        country_codes JSON         NOT NULL,
        country_count INT          NOT NULL DEFAULT 0,
        language_hint VARCHAR(100) NOT NULL DEFAULT '',
        remark        TEXT         DEFAULT NULL,
        status        VARCHAR(20)  NOT NULL DEFAULT 'active',
        usage_count   INT          NOT NULL DEFAULT 0,
        last_used_at  DATETIME     DEFAULT NULL,
        created_by    VARCHAR(100) NOT NULL DEFAULT '',
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_org (org_id),
        INDEX idx_status (status),
        INDEX idx_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # ═══════════════════════════════════════════════════════════════
    # SaaS 多租户元数据表（阶段 1 骨架，详见 docs/saas-transformation.md）
    # 仅新建表，不修改任何业务表；业务表的 tenant_id 列由迁移脚本提供。
    # 不带 tenant_id 的旧 JWT 默认归属 internal tenant (id=1)，向后兼容。
    # ═══════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS app_tenants (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        slug            VARCHAR(64)  NOT NULL UNIQUE COMMENT '租户唯一标识，用于子域名/路径',
        name            VARCHAR(200) NOT NULL,
        plan_id         VARCHAR(50)  NOT NULL DEFAULT 'free',
        status          VARCHAR(20)  NOT NULL DEFAULT 'active' COMMENT 'active/suspended/canceled',
        is_internal     TINYINT      NOT NULL DEFAULT 0 COMMENT '1=内部 AdsMind 短剧业务租户',
        enabled_plugins JSON         DEFAULT NULL COMMENT '启用插件列表，如 ["drama","optimizer"]',
        settings        JSON         DEFAULT NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_tenant_members (
        tenant_id  BIGINT NOT NULL,
        user_id    BIGINT NOT NULL,
        role       VARCHAR(50) NOT NULL DEFAULT 'member' COMMENT '租户内角色 owner/admin/member',
        joined_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (tenant_id, user_id),
        INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_plan_upgrade_requests (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id       BIGINT       NOT NULL,
        from_plan_id    VARCHAR(50)  NOT NULL,
        to_plan_id      VARCHAR(50)  NOT NULL,
        contact_email   VARCHAR(255) NOT NULL,
        message         TEXT         DEFAULT NULL,
        status          VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected/canceled',
        requested_by_user_id BIGINT  DEFAULT NULL,
        processed_by_user_id BIGINT  DEFAULT NULL,
        processed_at    DATETIME     DEFAULT NULL,
        admin_note      TEXT         DEFAULT NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_tenant (tenant_id),
        INDEX idx_status (status),
        INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_email_verifications (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id      BIGINT       NOT NULL,
        email        VARCHAR(255) NOT NULL,
        token        VARCHAR(64)  NOT NULL,
        purpose      VARCHAR(20)  NOT NULL DEFAULT 'register' COMMENT 'register/change',
        expires_at   DATETIME     NOT NULL,
        verified_at  DATETIME     DEFAULT NULL,
        created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_token (token),
        INDEX idx_user (user_id),
        INDEX idx_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_tenant_invitations (
        id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id          BIGINT       NOT NULL,
        email              VARCHAR(255) NOT NULL COMMENT '受邀人邮箱',
        role               VARCHAR(50)  NOT NULL DEFAULT 'member' COMMENT 'owner/admin/member',
        token              VARCHAR(64)  NOT NULL COMMENT '邀请 token，URL 中传递',
        expires_at         DATETIME     NOT NULL COMMENT '过期时间',
        accepted_at        DATETIME     DEFAULT NULL COMMENT '接受时间',
        accepted_user_id   BIGINT       DEFAULT NULL COMMENT '接受人 user_id',
        invited_by_user_id BIGINT       DEFAULT NULL COMMENT '邀请人 user_id',
        revoked_at         DATETIME     DEFAULT NULL COMMENT '撤销时间',
        created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_token (token),
        INDEX idx_tenant (tenant_id),
        INDEX idx_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_plans (
        id                  VARCHAR(50)  PRIMARY KEY,
        name                VARCHAR(100) NOT NULL,
        accounts_limit      INT          NOT NULL DEFAULT 1,
        api_calls_monthly   INT          NOT NULL DEFAULT 10000,
        ai_calls_monthly    INT          NOT NULL DEFAULT 0,
        sync_interval_min   INT          NOT NULL DEFAULT 60,
        data_retention_days INT          NOT NULL DEFAULT 30,
        price_monthly_cents INT          NOT NULL DEFAULT 0,
        features            JSON         DEFAULT NULL,
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_subscriptions (
        tenant_id    BIGINT PRIMARY KEY,
        plan_id      VARCHAR(50)  NOT NULL,
        period_start DATETIME     NOT NULL,
        period_end   DATETIME     NOT NULL,
        status       VARCHAR(20)  NOT NULL DEFAULT 'active' COMMENT 'active/past_due/canceled',
        external_ref VARCHAR(200) DEFAULT NULL COMMENT 'Stripe subscription id',
        source       VARCHAR(20)  NOT NULL DEFAULT 'self' COMMENT 'self=自助 / sales=销售开通',
        updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_status (status),
        INDEX idx_period_end (period_end)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_usage_counters (
        tenant_id BIGINT      NOT NULL,
        metric    VARCHAR(50) NOT NULL COMMENT 'api_calls/ai_calls/sync_runs',
        period_ym CHAR(7)     NOT NULL COMMENT '2026-05',
        value     BIGINT      NOT NULL DEFAULT 0,
        updated_at DATETIME   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (tenant_id, metric, period_ym)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_api_keys (
        id          BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id   BIGINT       NOT NULL,
        name        VARCHAR(100) NOT NULL,
        key_prefix  VARCHAR(16)  NOT NULL COMMENT 'API Key 前缀，明文展示',
        key_hash    VARCHAR(255) NOT NULL COMMENT 'API Key SHA-256 哈希',
        scopes      JSON         DEFAULT NULL,
        last_used_at DATETIME    DEFAULT NULL,
        revoked_at  DATETIME     DEFAULT NULL,
        created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_tenant (tenant_id),
        UNIQUE KEY uk_prefix (key_prefix)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_oauth_credentials (
        id                BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id         BIGINT       NOT NULL,
        platform          VARCHAR(20)  NOT NULL COMMENT 'tiktok/meta/google/oceanengine/snapchat',
        external_id       VARCHAR(100) NOT NULL COMMENT '平台侧账号或商户 ID',
        access_token_enc  LONGBLOB     NOT NULL COMMENT 'AES-256-GCM 加密：nonce||ciphertext||tag',
        refresh_token_enc LONGBLOB     DEFAULT NULL,
        expires_at        DATETIME     DEFAULT NULL,
        scopes            JSON         DEFAULT NULL,
        created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_tenant_platform_external (tenant_id, platform, external_id),
        INDEX idx_expires (expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_scheduled_jobs (
        id          BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id   BIGINT       NOT NULL,
        job_type    VARCHAR(50)  NOT NULL COMMENT 'sync_campaigns/sync_insights/refresh_tokens 等',
        config      JSON         NOT NULL,
        cron        VARCHAR(50)  NOT NULL,
        enabled     TINYINT      NOT NULL DEFAULT 1,
        last_run_at DATETIME     DEFAULT NULL,
        next_run_at DATETIME     DEFAULT NULL,
        created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_next_run (enabled, next_run_at),
        INDEX idx_tenant (tenant_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # ═══════════════════════════════════════════════════════════════
    # 阶段 4 应用配置模块（Tenant → Application 投放对象层）
    # 一个租户可创建多个 Application，每个 Application 是客户自主管理的
    # "投放对象"（一个 App / 一款游戏 / 一个产品），独立绑定广告账号 + 归因 + 看板。
    # 详见 docs/saas-transformation.md §22。
    # ═══════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS app_applications (
        id                BIGINT AUTO_INCREMENT PRIMARY KEY,
        tenant_id         BIGINT       NOT NULL COMMENT '归属租户',
        slug              VARCHAR(64)  NOT NULL COMMENT '应用 slug（tenant 内唯一）',
        name              VARCHAR(128) NOT NULL COMMENT '应用名称',
        description       VARCHAR(512) DEFAULT NULL,
        icon_url          VARCHAR(512) DEFAULT NULL,
        platform_type     VARCHAR(20)  NOT NULL DEFAULT 'multi'
                          COMMENT 'ios / android / web / mini_program / multi',
        bundle_id         VARCHAR(255) DEFAULT NULL COMMENT 'iOS bundle / Android package',
        store_url_ios     VARCHAR(512) DEFAULT NULL,
        store_url_android VARCHAR(512) DEFAULT NULL,
        industry          VARCHAR(64)  DEFAULT NULL COMMENT '行业（短剧/游戏/电商等）',
        status            VARCHAR(20)  NOT NULL DEFAULT 'active'
                          COMMENT 'active / archived',
        is_default        TINYINT      NOT NULL DEFAULT 0 COMMENT '1=租户默认应用，旧数据兜底',
        settings_json     JSON         DEFAULT NULL COMMENT '灵活配置：归因/回传/默认目标地区等',
        created_by        BIGINT       DEFAULT NULL,
        created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_tenant_slug (tenant_id, slug),
        INDEX idx_tenant_status (tenant_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_application_members (
        application_id BIGINT      NOT NULL,
        user_id        BIGINT      NOT NULL,
        role           VARCHAR(20) NOT NULL DEFAULT 'editor'
                       COMMENT 'owner / admin / editor / viewer',
        joined_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (application_id, user_id),
        INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


_PANEL_SEED = [
    ("dashboard",          "首页概览",      "首页概览",   "/dashboard",          10),
    # 运营数据面板（仅超管可见，see _ROLE_DEFAULT_PANELS）
    ("ops_dashboard",      "运营数据",      "首页概览",   "/dashboard/ops",      11),
    ("ads_data",           "广告数据",      "投放管理",   "/ads",                20),
    ("tiktok_console",     "TikTok操作台",  "投放管理",   "/console/tiktok",     21),
    ("meta_console",       "Meta操作台",    "投放管理",   "/console/meta",       22),
    ("ad_create",          "新建广告",      "投放管理",   "/ads/create",         23),
    ("template_mgmt",      "模板管理",      "投放管理",   "/templates",          24),
    ("creatives",          "素材库",        "素材中心",   "/creatives",          30),
    ("creative_analysis",  "素材分析",      "素材中心",   "/creative-analysis",  31),
    ("overview",           "数据总览",      "数据分析",   "/overview",           40),
    ("channel_analysis",   "渠道分析",      "数据分析",   "/channel-analysis",   41),
    ("biz_analysis",       "业务分析",      "数据分析",   "/biz-analysis",       42),
    ("data_compare",           "数据对比",        "数据对比",   "/data-compare",            50),
    # 广告回传分析（过渡版，回传口径，非订单真值）
    ("returned_conversion",    "广告回传分析",    "数据分析",   "/returned-conversion",     43),
    # 剧级分析
    ("drama_analysis",         "剧级分析",        "数据分析",   "/drama-analysis",          44),
    # 设计师人效报表
    ("designer_performance",   "设计师人效",      "素材中心",   "/designer-performance",    32),
    # 优化师人效报表
    ("optimizer_performance",  "优化师人效",      "数据分析",   "/optimizer-performance",   45),
    ("data_source",            "数据源配置",      "系统管理",   "/data-source",             60),
    ("user_mgmt",              "用户权限",        "系统管理",   "/user-mgmt",               61),
    ("role_perm",              "角色权限管理",    "系统管理",   "/role-perm",               62),
    ("insight_config",         "ROI阈值配置",     "系统管理",   "/insight-config",          63),
    ("oplog",                  "操作日志",        "系统管理",   "/oplog",                   64),
    ("optimizer_directory",    "优化师名单配置",  "系统管理",   "/optimizer-directory",     65),
    # 阶段 4 X1：应用配置模块
    ("applications",           "应用管理",        "系统管理",   "/applications",            66),
    # 阶段 7：团队邀请
    ("team",                   "团队成员",        "系统管理",   "/team",                    67),
    # 广告资产库
    ("asset_landing_pages",    "落地页库",        "广告资产库", "/assets/landing-pages",    70),
    ("asset_copy_packs",       "文案库",          "广告资产库", "/assets/copy-packs",       71),
    ("asset_region_groups",    "地区组库",        "广告资产库", "/assets/region-groups",    72),
    # TikTok 素材上传
    ("tiktok_materials",       "TikTok素材上传",  "素材中心",   "/tiktok-materials",       33),
]

_ROLE_DEFAULT_PANELS: dict[str, list[str]] = {
    "super_admin": [p[0] for p in _PANEL_SEED],
    # admin 不含 role_perm（角色权限管理）和 ops_dashboard（运营数据，超管专属）
    "admin":       [p[0] for p in _PANEL_SEED if p[0] not in ("role_perm", "ops_dashboard")],
    "optimizer":   ["dashboard", "ads_data", "tiktok_console", "meta_console", "ad_create",
                    "template_mgmt", "creatives", "creative_analysis", "optimizer_performance",
                    "optimizer_directory", "designer_performance", "drama_analysis",
                    "returned_conversion", "oplog",
                    "asset_landing_pages", "asset_copy_packs", "asset_region_groups",
                    "tiktok_materials"],
    "designer":    ["dashboard", "creatives", "creative_analysis", "designer_performance"],
    "analyst":     ["dashboard", "overview", "channel_analysis", "biz_analysis", "data_compare",
                    "creative_analysis", "returned_conversion", "drama_analysis", "designer_performance",
                    "optimizer_performance"],
    "viewer":      ["dashboard"],
}


def init_app_tables():
    """在应用库中创建元数据表（幂等）。启动时调用。"""
    try:
        conn = _create_app_conn()
    except Exception as e:
        logger.warning(f"init_app_tables: APP 应用库连接失败，跳过建表: {e}")
        return
    try:
        cur = conn.cursor()
        for sql in _APP_TABLES_SQL:
            cur.execute(sql)
        conn.commit()
        _seed_panels(cur, conn)
        _seed_role_panels(cur, conn)
        _migrate_super_admin_ops_dashboard_user_override(cur, conn)
        _seed_insight_config(cur, conn)
        _seed_default_plans(cur, conn)
        _seed_internal_tenant(cur, conn)
        _seed_internal_default_application(cur, conn)
        _migrate_rebrand_adpilot_to_adsmind(cur, conn)
        _migrate_app_users_email_verified(cur, conn)
        logger.info("APP 应用库元数据表初始化完成")
    except Exception as e:
        logger.error(f"init_app_tables 失败: {e}")
    finally:
        conn.close()


def _seed_panels(cur, conn):
    """幂等：将 _PANEL_SEED 中缺失的面板补充写入 panel_definitions（INSERT IGNORE）"""
    count = 0
    for panel_key, panel_name, panel_group, route_path, sort_order in _PANEL_SEED:
        cur.execute(
            """INSERT IGNORE INTO panel_definitions
               (panel_key, panel_name, panel_group, route_path, sort_order)
               VALUES (%s, %s, %s, %s, %s)""",
            (panel_key, panel_name, panel_group, route_path, sort_order),
        )
        count += cur.rowcount
    conn.commit()
    if count:
        logger.info(f"已补充写入 {count} 条面板定义种子数据")


def _seed_role_panels(cur, conn):
    """幂等：将 _ROLE_DEFAULT_PANELS 中缺失的角色面板权限补充写入（INSERT IGNORE）"""
    count = 0
    for role_key, panels in _ROLE_DEFAULT_PANELS.items():
        for panel_key in panels:
            cur.execute(
                """INSERT IGNORE INTO role_panel_permissions (role_key, panel_key, can_view)
                   VALUES (%s, %s, 1)""",
                (role_key, panel_key),
            )
            count += cur.rowcount
    conn.commit()
    if count:
        logger.info(f"已补充写入 {count} 条角色默认面板权限")


def _migrate_super_admin_ops_dashboard_user_override(cur, conn):
    """幂等：super_admin 若启用了用户级面板覆盖但缺少 ops_dashboard，则补一行。

    resolve_user_allowed_panels 在存在 user_panel_permissions 时只返回用户列表、
    不再合并角色默认；历史上部分账号只有 tiktok_materials 等少数面板，
    会导致 /api/ops/daily-stats 403。补全后运营面板与路由权限一致。
    """
    cur.execute(
        """
        SELECT DISTINCT u.username
        FROM app_users u
        INNER JOIN user_panel_permissions up
            ON up.username = u.username AND up.can_view = 1
        WHERE u.role = 'super_admin'
          AND NOT EXISTS (
              SELECT 1 FROM user_panel_permissions x
              WHERE x.username = u.username
                AND x.panel_key = 'ops_dashboard'
                AND x.can_view = 1
          )
        """
    )
    names = [r["username"] for r in cur.fetchall()]
    if not names:
        return
    for username in names:
        cur.execute(
            """INSERT IGNORE INTO user_panel_permissions (username, panel_key, can_view)
               VALUES (%s, 'ops_dashboard', 1)""",
            (username,),
        )
    conn.commit()
    logger.info(
        "super_admin 用户面板覆盖补全: 已为 %s 个账号写入 ops_dashboard",
        len(names),
    )


def _seed_insight_config(cur, conn):
    """幂等：仅当 app_insight_config 为空时写入默认 ROI 阈值"""
    cur.execute("SELECT COUNT(*) AS cnt FROM app_insight_config")
    if cur.fetchone()["cnt"] > 0:
        return
    import json as _json
    default_roi = _json.dumps({"min": 0.1, "low": 0.8, "target": 1.2, "high": 2.0})
    cur.execute(
        "INSERT INTO app_insight_config (config_key, config_value) VALUES (%s, %s)",
        ("roi_thresholds", default_roi),
    )
    conn.commit()
    logger.info("已写入 Insight 默认 ROI 阈值配置")


# ─── SaaS 多租户骨架 seed（阶段 1） ───────────────────────────────

_DEFAULT_PLANS_SEED = [
    # (id, name, accounts_limit, api_calls_monthly, ai_calls_monthly,
    #  sync_interval_min, data_retention_days, price_monthly_cents, features)
    ("internal",   "Internal",     999, 99999999, 99999999,  5, 3650,    0,
     '{"all_plugins": true}'),
    ("free",       "Free",           1,    5000,        0, 60,   30,    0,
     '{"plugins": ["core_ads"]}'),
    ("starter",    "Starter",        3,   50000,      100, 30,   90, 4900,
     '{"plugins": ["core_ads","ai_studio"]}'),
    ("pro",        "Pro",           10,  300000,     1000, 15,  180, 19900,
     '{"plugins": ["core_ads","ai_studio"]}'),
    ("business",   "Business",      30, 1000000,     5000, 10,  365, 49900,
     '{"plugins": ["core_ads","ai_studio"]}'),
    ("enterprise", "Enterprise",   999, 99999999,   99999, 5,  3650, 0,
     '{"plugins": ["core_ads","ai_studio"], "custom_sla": true}'),
]


def _seed_default_plans(cur, conn):
    """幂等：补齐默认套餐种子（INSERT IGNORE，已存在则不动）"""
    count = 0
    for (pid, name, acc, api_m, ai_m, sync_min, retent, price, features) in _DEFAULT_PLANS_SEED:
        cur.execute(
            """INSERT IGNORE INTO app_plans
               (id, name, accounts_limit, api_calls_monthly, ai_calls_monthly,
                sync_interval_min, data_retention_days, price_monthly_cents, features)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (pid, name, acc, api_m, ai_m, sync_min, retent, price, features),
        )
        count += cur.rowcount
    conn.commit()
    if count:
        logger.info(f"已补充写入 {count} 条默认套餐种子")


def _migrate_app_users_email_verified(cur, conn):
    """阶段 7 #3：给 app_users 表加 email_verified_at 列（幂等）。

    历史用户保留 NULL（视为已"老用户豁免"，前端不强弹验证 banner）；
    新通过 /api/auth/register 注册的用户会立即创建 verification 记录，
    一旦点验证链接后回填 verified_at + 同步更新 app_users.email_verified_at。
    """
    try:
        cur.execute("""SHOW COLUMNS FROM app_users LIKE 'email_verified_at'""")
        exists = cur.fetchone() is not None
        if exists:
            return
        cur.execute("""ALTER TABLE app_users
                       ADD COLUMN email_verified_at DATETIME NULL DEFAULT NULL
                       COMMENT '邮箱验证时间；NULL 表示历史用户或未验证' """)
        conn.commit()
        logger.info("迁移：app_users 已新增 email_verified_at 列")
    except Exception as e:
        logger.warning(f"迁移 email_verified_at 失败（不影响启动）：{e}")


def _migrate_rebrand_adpilot_to_adsmind(cur, conn):
    """幂等：把历史播种数据中的产品名 'AdPilot' 替换成 'AdsMind'。

    只命中 seed 函数曾经写入的固定字符串（tenant_id=1 的 name 字段、
    is_default=1 的 application name），不影响其它用户数据。

    旧值                  → 新值
      AdPilot 内部         → AdsMind 内部
      AdPilot 默认应用     → AdsMind 默认应用
    """
    try:
        cur.execute(
            """UPDATE app_tenants
               SET name = 'AdsMind 内部'
               WHERE id = 1 AND name = 'AdPilot 内部'"""
        )
        n1 = cur.rowcount
        cur.execute(
            """UPDATE app_applications
               SET name = 'AdsMind 默认应用'
               WHERE is_default = 1 AND name = 'AdPilot 默认应用'"""
        )
        n2 = cur.rowcount
        conn.commit()
        if n1 + n2:
            logger.info(f"rebrand 迁移：tenant 重命名 {n1} 行，application 重命名 {n2} 行")
    except Exception as e:
        logger.warning(f"rebrand 迁移失败（不影响启动）：{e}")


def _seed_internal_default_application(cur, conn):
    """幂等：为 internal tenant (id=1) 创建一个默认应用 (id=1)。

    所有未显式归属应用的现存数据（biz_ad_accounts 等）通过迁移脚本 003
    回填到这个 default application，向后兼容。

    详见 docs/saas-transformation.md §22。
    """
    cur.execute("SELECT id FROM app_applications WHERE tenant_id = 1 AND is_default = 1 LIMIT 1")
    if cur.fetchone():
        return
    import json as _json
    settings = _json.dumps({
        "default_currency": "USD",
        "default_timezone": "Asia/Shanghai",
        "attribution": {"provider": "metis", "window_days": 121},
    })
    cur.execute(
        """INSERT INTO app_applications
           (tenant_id, slug, name, description, platform_type, industry,
            status, is_default, settings_json)
           VALUES (1, 'default', 'AdsMind 默认应用',
                   '内部租户的默认应用，承载现有所有业务数据',
                   'multi', 'drama_overseas', 'active', 1, %s)""",
        (settings,),
    )
    conn.commit()
    logger.info("已为 internal tenant 创建 default application")


def _seed_internal_tenant(cur, conn):
    """幂等：确保 id=1 的 internal 租户存在；用于现有数据兜底归属。

    详见 docs/saas-transformation.md §6.3。
    """
    cur.execute("SELECT id FROM app_tenants WHERE id = 1")
    if cur.fetchone():
        return
    import json as _json
    enabled = _json.dumps([
        "core_ads",
        "drama",
        "optimizer",
        "attribution_metis",
        "returned_conversion",
        "ops_panel_polardb",
    ])
    cur.execute(
        """INSERT INTO app_tenants (id, slug, name, plan_id, status, is_internal, enabled_plugins)
           VALUES (1, 'internal', 'AdsMind 内部', 'internal', 'active', 1, %s)""",
        (enabled,),
    )
    conn.commit()
    logger.info("已创建 internal 租户 (id=1)，启用全部插件")


# ═══════════════════════════════════════════════════════════
#  业务库建表（全部使用 _create_biz_conn）
# ═══════════════════════════════════════════════════════════

_BIZ_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS biz_ad_accounts (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL COMMENT 'tiktok / meta',
        account_id      VARCHAR(100)  NOT NULL COMMENT '平台侧账户ID',
        account_name    VARCHAR(255)  NOT NULL DEFAULT '',
        currency        VARCHAR(10)   NOT NULL DEFAULT 'USD',
        timezone        VARCHAR(50)   NOT NULL DEFAULT 'UTC',
        status          VARCHAR(30)   NOT NULL DEFAULT 'ACTIVE',
        access_token    TEXT          DEFAULT NULL COMMENT '平台 Access Token',
        app_id          VARCHAR(200)  NOT NULL DEFAULT '' COMMENT 'TikTok App ID',
        app_secret      VARCHAR(200)  NOT NULL DEFAULT '' COMMENT 'TikTok App Secret',
        is_default      TINYINT       NOT NULL DEFAULT 0 COMMENT '是否为默认账户',
        last_synced_at  DATETIME      DEFAULT NULL COMMENT '上次数据同步时间',
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_account (platform, account_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_campaigns (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL,
        campaign_name   VARCHAR(500)  NOT NULL DEFAULT '',
        objective       VARCHAR(100)  NOT NULL DEFAULT '',
        buying_type     VARCHAR(50)   NOT NULL DEFAULT '',
        status          VARCHAR(50)   NOT NULL DEFAULT '',
        is_active       TINYINT       NOT NULL DEFAULT 1,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_campaign (platform, campaign_id),
        INDEX idx_platform_account (platform, account_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_campaign_daily_normalized (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL,
        campaign_name   VARCHAR(500)  NOT NULL DEFAULT '',
        stat_date       DATE          NOT NULL,
        spend           DECIMAL(14,4) NOT NULL DEFAULT 0,
        impressions     BIGINT        NOT NULL DEFAULT 0,
        clicks          BIGINT        NOT NULL DEFAULT 0,
        installs        BIGINT        NOT NULL DEFAULT 0,
        conversions     BIGINT        NOT NULL DEFAULT 0,
        revenue         DECIMAL(14,4) NOT NULL DEFAULT 0,
        ctr             DECIMAL(10,6) DEFAULT NULL,
        cpc             DECIMAL(10,4) DEFAULT NULL,
        cpm             DECIMAL(10,4) DEFAULT NULL,
        cpi             DECIMAL(10,4) DEFAULT NULL,
        cpa             DECIMAL(10,4) DEFAULT NULL,
        roas            DECIMAL(10,4) DEFAULT NULL,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_campaign_date (platform, campaign_id, stat_date),
        INDEX idx_stat_date (stat_date),
        INDEX idx_platform_account_date (platform, account_id, stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_adgroups (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL DEFAULT '',
        adgroup_id      VARCHAR(100)  NOT NULL,
        adgroup_name    VARCHAR(500)  NOT NULL DEFAULT '',
        status          VARCHAR(50)   NOT NULL DEFAULT '',
        is_active       TINYINT       NOT NULL DEFAULT 1,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_adgroup (platform, adgroup_id),
        INDEX idx_platform_campaign (platform, campaign_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_adgroup_daily_normalized (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL DEFAULT '',
        campaign_name   VARCHAR(500)  NOT NULL DEFAULT '',
        adgroup_id      VARCHAR(100)  NOT NULL,
        adgroup_name    VARCHAR(500)  NOT NULL DEFAULT '',
        stat_date       DATE          NOT NULL,
        spend           DECIMAL(14,4) NOT NULL DEFAULT 0,
        impressions     BIGINT        NOT NULL DEFAULT 0,
        clicks          BIGINT        NOT NULL DEFAULT 0,
        installs        BIGINT        NOT NULL DEFAULT 0,
        conversions     BIGINT        NOT NULL DEFAULT 0,
        revenue         DECIMAL(14,4) NOT NULL DEFAULT 0,
        ctr             DECIMAL(10,6) DEFAULT NULL,
        cpc             DECIMAL(10,4) DEFAULT NULL,
        cpm             DECIMAL(10,4) DEFAULT NULL,
        cpi             DECIMAL(10,4) DEFAULT NULL,
        cpa             DECIMAL(10,4) DEFAULT NULL,
        roas            DECIMAL(10,4) DEFAULT NULL,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_adgroup_date (platform, adgroup_id, stat_date),
        INDEX idx_stat_date (stat_date),
        INDEX idx_platform_account_date (platform, account_id, stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_ad_daily_normalized (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL DEFAULT '',
        campaign_name   VARCHAR(500)  NOT NULL DEFAULT '',
        adgroup_id      VARCHAR(100)  NOT NULL DEFAULT '',
        adgroup_name    VARCHAR(500)  NOT NULL DEFAULT '',
        ad_id           VARCHAR(100)  NOT NULL,
        ad_name         VARCHAR(500)  NOT NULL DEFAULT '',
        stat_date       DATE          NOT NULL,
        spend           DECIMAL(14,4) NOT NULL DEFAULT 0,
        impressions     BIGINT        NOT NULL DEFAULT 0,
        clicks          BIGINT        NOT NULL DEFAULT 0,
        installs        BIGINT        NOT NULL DEFAULT 0,
        conversions     BIGINT        NOT NULL DEFAULT 0,
        revenue         DECIMAL(14,4) NOT NULL DEFAULT 0,
        ctr             DECIMAL(10,6) DEFAULT NULL,
        cpc             DECIMAL(10,4) DEFAULT NULL,
        cpm             DECIMAL(10,4) DEFAULT NULL,
        cpi             DECIMAL(10,4) DEFAULT NULL,
        cpa             DECIMAL(10,4) DEFAULT NULL,
        roas            DECIMAL(10,4) DEFAULT NULL,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_ad_date (platform, ad_id, stat_date),
        INDEX idx_stat_date (stat_date),
        INDEX idx_platform_account_date (platform, account_id, stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_ads (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform        VARCHAR(20)   NOT NULL,
        account_id      VARCHAR(100)  NOT NULL,
        campaign_id     VARCHAR(100)  NOT NULL DEFAULT '',
        adgroup_id      VARCHAR(100)  NOT NULL DEFAULT '',
        ad_id           VARCHAR(100)  NOT NULL,
        ad_name         VARCHAR(500)  NOT NULL DEFAULT '',
        status          VARCHAR(50)   NOT NULL DEFAULT '',
        is_active       TINYINT       NOT NULL DEFAULT 1,
        raw_json        JSON          DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_ad (platform, ad_id),
        INDEX idx_platform_adgroup (platform, adgroup_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    -- 广告回传转化日报表（回传口径，非订单真值，存储于 BIZ 业务库）
    -- data_label = 'returned' 标识本表全部数据为广告平台归因回传口径
    CREATE TABLE IF NOT EXISTS ad_returned_conversion_daily (
        id                       BIGINT         AUTO_INCREMENT PRIMARY KEY,
        stat_date                DATE           NOT NULL COMMENT '统计日期',
        media_source             VARCHAR(50)    NOT NULL COMMENT '媒体来源: meta / tiktok / google',
        account_id               VARCHAR(100)   DEFAULT NULL COMMENT '广告账户ID',
        campaign_id              VARCHAR(100)   DEFAULT NULL COMMENT '广告系列ID',
        campaign_name            VARCHAR(255)   DEFAULT NULL COMMENT '广告系列名称',
        adset_id                 VARCHAR(100)   DEFAULT NULL COMMENT '广告组ID',
        adset_name               VARCHAR(255)   DEFAULT NULL COMMENT '广告组名称',
        ad_id                    VARCHAR(100)   DEFAULT NULL COMMENT '广告ID',
        ad_name                  VARCHAR(255)   DEFAULT NULL COMMENT '广告名称',
        country                  VARCHAR(50)    DEFAULT NULL COMMENT '国家/地区',
        platform                 VARCHAR(50)    DEFAULT NULL COMMENT '操作系统平台: ios / android / mixed',
        impressions              BIGINT         NOT NULL DEFAULT 0 COMMENT '展示量',
        clicks                   BIGINT         NOT NULL DEFAULT 0 COMMENT '点击量',
        installs                 BIGINT         NOT NULL DEFAULT 0 COMMENT '安装量',
        spend                    DECIMAL(18,4)  NOT NULL DEFAULT 0 COMMENT '广告花费',
        -- 以下字段均为广告平台归因回传口径，非后端订单真值 --
        registrations_returned   BIGINT         NOT NULL DEFAULT 0 COMMENT '回传注册数（平台归因）',
        purchase_value_returned  DECIMAL(18,4)  NOT NULL DEFAULT 0 COMMENT '回传充值价值（平台归因）',
        purchase_count_returned  BIGINT         NOT NULL DEFAULT 0 COMMENT '回传内购数/购买次数（平台归因）',
        subscribe_value_returned DECIMAL(18,4)  NOT NULL DEFAULT 0 COMMENT '回传订阅价值（平台归因，不支持时为0）',
        subscribe_count_returned BIGINT         NOT NULL DEFAULT 0 COMMENT '回传订阅数/订阅次数（平台归因，不支持时为0）',
        total_value_returned     DECIMAL(18,4)  NOT NULL DEFAULT 0 COMMENT '回传总价值 = purchase + subscribe',
        d0_roi_returned          DECIMAL(18,6)  NOT NULL DEFAULT 0 COMMENT 'D0 ROI 回传口径 = total_value / spend',
        d1_value_returned        DECIMAL(18,4)  NOT NULL DEFAULT 0 COMMENT 'D1 回传价值（仅平台支持时有值）',
        d1_roi_returned          DECIMAL(18,6)  NOT NULL DEFAULT 0 COMMENT 'D1 ROI 回传口径 = d1_value / spend',
        -- 首日（D0 Cohort）拆分字段，需平台支持 D0 cohort 上报时才有值，默认 0 --
        d0_registrations_returned    BIGINT        NOT NULL DEFAULT 0 COMMENT '首日注册数（D0 cohort，平台支持时有值）',
        d0_purchase_value_returned   DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '首日充值金额（D0 cohort，平台支持时有值）',
        d0_subscribe_value_returned  DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '首日订阅金额（D0 cohort，平台支持时有值）',
        data_label               VARCHAR(50)    NOT NULL DEFAULT 'returned' COMMENT '数据口径标识，固定为 returned',
        raw_payload              JSON           DEFAULT NULL COMMENT '原始平台数据，用于追溯字段来源',
        created_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_returned_daily (stat_date, media_source, account_id, campaign_id, adset_id, ad_id, country, platform),
        INDEX idx_stat_date (stat_date),
        INDEX idx_media_source (media_source),
        INDEX idx_account_date (account_id, stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='广告回传转化日报 — 回传口径，非订单真值，存储在 adpilot_biz 业务库'
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_sync_logs (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        task_name       VARCHAR(100)  NOT NULL,
        platform        VARCHAR(20)   NOT NULL DEFAULT '',
        account_id      VARCHAR(100)  NOT NULL DEFAULT '',
        sync_date       DATE          DEFAULT NULL,
        status          VARCHAR(20)   NOT NULL DEFAULT 'running',
        message         TEXT          DEFAULT NULL,
        rows_affected   INT           NOT NULL DEFAULT 0,
        started_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at     DATETIME      DEFAULT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_task_date (task_name, sync_date),
        INDEX idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # ─── 剧级映射表：存储每条广告活动的剧名解析结果 ───────────────────
    """
    CREATE TABLE IF NOT EXISTS ad_drama_mapping (
        id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
        source_type          VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '来源类型: 小程序 / APP',
        platform             VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '媒体平台: tiktok / meta',
        channel              VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '渠道标识',
        account_id           VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '广告账户ID',
        campaign_id          VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '活动ID',
        campaign_name        TEXT          NOT NULL COMMENT '原始活动名称',
        adset_id             VARCHAR(100)  NOT NULL DEFAULT '',
        adset_name           VARCHAR(500)  NOT NULL DEFAULT '',
        ad_id                VARCHAR(100)  NOT NULL DEFAULT '',
        ad_name              VARCHAR(500)  NOT NULL DEFAULT '',

        drama_id             VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '剧集ID（小程序解析得到；APP暂留）',
        drama_type           VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '剧集类型，如 AIGC',
        country              VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '国家/地区代码',

        drama_name_raw       VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '第10字段原始剧名（唯一合法来源）',
        localized_drama_name VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '去掉语言尾缀的剧名',
        language_code        VARCHAR(10)   NOT NULL DEFAULT 'unknown' COMMENT '语言代码，未识别为 unknown',
        language_tag_raw     VARCHAR(20)   DEFAULT NULL COMMENT '原始语言标记，如 (EN)',

        buyer_name           VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '投手姓名（小程序字段6）',
        buyer_short_name     VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '投手简称（APP字段11）',
        optimization_type    VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '优化目标',
        bid_type             VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '出价类型',
        publish_date         VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '发布日期，格式 YYYYMMDD',

        remark_raw           TEXT          DEFAULT NULL COMMENT '备注原文（第11+字段），不参与任何解析',

        content_key          VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '剧内容唯一键：小程序=drama_id，APP=normalized(localized_drama_name)',
        match_source         VARCHAR(50)   NOT NULL DEFAULT 'parser' COMMENT '映射来源: parser / manual',
        is_confirmed         TINYINT       NOT NULL DEFAULT 0 COMMENT '是否人工确认',
        parse_status         VARCHAR(20)   NOT NULL DEFAULT 'ok' COMMENT 'ok / partial / failed',
        parse_error          TEXT          DEFAULT NULL COMMENT '解析失败原因',

        created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_campaign (platform, account_id, campaign_id),
        INDEX idx_content_key (content_key(191)),
        INDEX idx_drama_id (drama_id),
        INDEX idx_language (language_code),
        INDEX idx_source_type (source_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='广告活动剧名解析映射表'
    """,
    # ─── 剧级日报事实表：聚合后的每日投放数据 ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fact_drama_daily (
        id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
        stat_date            DATE          NOT NULL COMMENT '统计日期',
        source_type          VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '来源类型: 小程序 / APP',
        platform             VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '媒体平台: tiktok / meta',
        channel              VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '渠道标识',
        account_id           VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '广告账户ID',
        country              VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '国家/地区代码',

        drama_id             VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '剧集ID',
        drama_type           VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '剧集类型',
        localized_drama_name VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '本地化剧名（不含语言尾缀）',
        language_code        VARCHAR(10)   NOT NULL DEFAULT 'unknown' COMMENT '语言代码',
        content_key          VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '剧内容唯一键',

        spend                DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '花费（USD）',
        impressions          BIGINT        NOT NULL DEFAULT 0 COMMENT '展示次数',
        clicks               BIGINT        NOT NULL DEFAULT 0 COMMENT '点击次数',
        installs             BIGINT        NOT NULL DEFAULT 0 COMMENT '安装数',
        registrations        BIGINT        NOT NULL DEFAULT 0 COMMENT '注册数',
        purchase_value       DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '购买/充值价值',

        created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_drama_daily (stat_date, source_type, platform, channel, account_id, country, content_key(191), language_code),
        INDEX idx_content_key (content_key(191)),
        INDEX idx_stat_date (stat_date),
        INDEX idx_drama_id (drama_id),
        INDEX idx_language (language_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='剧级日报事实表（按 content_key + language_code 聚合）'
    """,
    # ─── 优化师-Campaign 映射表 ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS campaign_optimizer_mapping (
        id                        BIGINT AUTO_INCREMENT PRIMARY KEY,
        source_type               VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '来源类型: 小程序 / APP',
        platform                  VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '媒体平台: tiktok / meta',
        channel                   VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '渠道标识',
        account_id                VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '广告账户ID',
        campaign_id               VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '活动ID',
        campaign_name             TEXT          NOT NULL COMMENT '原始活动名称',

        optimizer_name_raw        VARCHAR(200)  NOT NULL DEFAULT '' COMMENT '解析出的原始优化师名称',
        optimizer_name_normalized VARCHAR(200)  NOT NULL DEFAULT '未识别' COMMENT '标准化优化师名称（大写去空格）',
        optimizer_source          VARCHAR(50)   NOT NULL DEFAULT 'campaign_name' COMMENT '优化师来源: campaign_name / structured',

        parse_status              VARCHAR(20)   NOT NULL DEFAULT 'ok' COMMENT 'ok / failed',
        parse_error               TEXT          DEFAULT NULL COMMENT '解析失败原因',

        created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_optimizer_campaign (source_type, platform, account_id, campaign_id),
        INDEX idx_optimizer_name (optimizer_name_normalized),
        INDEX idx_source_type (source_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='Campaign 到优化师的映射表'
    """,
    # ─── 优化师日报事实表 ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fact_optimizer_daily (
        id                        BIGINT AUTO_INCREMENT PRIMARY KEY,
        stat_date                 DATE          NOT NULL COMMENT '统计日期',
        source_type               VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '来源类型: 小程序 / APP',
        platform                  VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '媒体平台: tiktok / meta',
        channel                   VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '渠道标识',
        account_id                VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '广告账户ID',
        country                   VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '国家/地区代码',
        optimizer_name            VARCHAR(200)  NOT NULL DEFAULT '未识别' COMMENT '优化师名称（标准化）',

        spend                     DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '花费（USD）',
        impressions               BIGINT        NOT NULL DEFAULT 0 COMMENT '展示次数',
        clicks                    BIGINT        NOT NULL DEFAULT 0 COMMENT '点击次数',
        installs                  BIGINT        NOT NULL DEFAULT 0 COMMENT '安装数',
        registrations             BIGINT        NOT NULL DEFAULT 0 COMMENT '注册数',
        purchase_value            DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '购买/充值价值',
        campaign_count            INT           NOT NULL DEFAULT 0 COMMENT '关联Campaign数',

        created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_optimizer_daily (stat_date, source_type, platform, channel, account_id, country, optimizer_name),
        INDEX idx_optimizer_name (optimizer_name),
        INDEX idx_stat_date (stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='优化师日报事实表'
    """,
    # ─── 优化师默认规则表 ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS optimizer_default_rules (
        id                        BIGINT AUTO_INCREMENT PRIMARY KEY,
        source_type               VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '来源类型: 小程序 / APP / 空=全部',
        platform                  VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '媒体平台: tiktok / meta / 空=全部',
        channel                   VARCHAR(50)   NOT NULL DEFAULT '' COMMENT '渠道标识 / 空=全部',
        account_id                VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '广告账户ID / 空=全部',
        country                   VARCHAR(20)   NOT NULL DEFAULT '' COMMENT '国家代码 / 空=全部',
        optimizer_name            VARCHAR(200)  NOT NULL COMMENT '匹配到的优化师名称',
        priority                  INT           NOT NULL DEFAULT 0 COMMENT '优先级（越大越高）',
        is_enabled                TINYINT       NOT NULL DEFAULT 1 COMMENT '是否启用',
        created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_priority (priority DESC),
        INDEX idx_enabled (is_enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='优化师默认兜底规则表'
    """,
    # ─── 优化师名单表 ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS optimizer_directory (
        id                        BIGINT AUTO_INCREMENT PRIMARY KEY,
        optimizer_name            VARCHAR(200)  NOT NULL COMMENT '标准名称',
        optimizer_code            VARCHAR(100)  NOT NULL COMMENT '唯一编码',
        aliases                   VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '别名，逗号分隔',
        is_active                 TINYINT       NOT NULL DEFAULT 1 COMMENT '是否启用',
        remark                    VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '备注',
        created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_optimizer_code (optimizer_code),
        INDEX idx_optimizer_name (optimizer_name),
        INDEX idx_is_active (is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='优化师名单配置表'
    """,
    # ─── TikTok 素材上传记录表 ────────────────────────
    # ─── 归因日报（来自 metis_dw.ads_ad_delivery_di，经 CK 同步进 BIZ）────────
    """
    CREATE TABLE IF NOT EXISTS biz_attribution_ad_daily (
        id                       BIGINT AUTO_INCREMENT PRIMARY KEY,

        -- ── 时间 / 时区 ───────────────────────────────────────────
        ds_la                    DATE          NOT NULL COMMENT '上游原始 LA cohort 日（America/Los_Angeles）',
        ds_account_local         DATE          NOT NULL COMMENT '按账户时区近似的 cohort 日（LA+Phoenix 当前等于 ds_la）',
        account_timezone         VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '账户实际 IANA 时区',
        timezone_source          VARCHAR(20)   NOT NULL DEFAULT '' COMMENT 'account_dim / media_fact / fallback',

        -- ── 维度 ─────────────────────────────────────────────────
        platform                 VARCHAR(20)   NOT NULL COMMENT '媒体源 lower：tiktok / facebook / google / ...',
        account_id               VARCHAR(100)  NOT NULL,
        account_name             VARCHAR(500)  NOT NULL DEFAULT '',
        account_status           VARCHAR(50)   NOT NULL DEFAULT '',
        campaign_id              VARCHAR(100)  NOT NULL DEFAULT '',
        campaign_name            VARCHAR(500)  NOT NULL DEFAULT '',
        delivery_method          VARCHAR(100)  NOT NULL DEFAULT '' COMMENT 'campaign_name 第 1 段',
        operator_id              VARCHAR(100)  NOT NULL DEFAULT '' COMMENT 'campaign_name 第 2 段：投手 ID',
        content_id               BIGINT        NOT NULL DEFAULT 0 COMMENT 'campaign_name 第 4 段：剧 ID',
        objective_type           VARCHAR(100)  NOT NULL DEFAULT '',
        budget_mode              VARCHAR(50)   NOT NULL DEFAULT '',
        budget_amount            DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '预算金额 USD',
        adgroup_id               VARCHAR(100)  NOT NULL DEFAULT '',
        adgroup_name             VARCHAR(500)  NOT NULL DEFAULT '',
        optimize_goal            VARCHAR(100)  NOT NULL DEFAULT '',
        bid_type                 VARCHAR(50)   NOT NULL DEFAULT '',
        ad_id                    VARCHAR(100)  NOT NULL,
        ad_name                  VARCHAR(500)  NOT NULL DEFAULT '',
        creative_id              VARCHAR(100)  NOT NULL DEFAULT '',
        video_id                 VARCHAR(100)  NOT NULL DEFAULT '',
        ad_status                VARCHAR(50)   NOT NULL DEFAULT '',

        -- ── 投放原子指标（媒体口径）──────────────────────────────
        spend                    DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '花费 USD',
        impressions              BIGINT        NOT NULL DEFAULT 0,
        clicks                   BIGINT        NOT NULL DEFAULT 0,
        inline_link_clicks       BIGINT        NOT NULL DEFAULT 0,
        landing_page_view        BIGINT        NOT NULL DEFAULT 0,
        conversion               BIGINT        NOT NULL DEFAULT 0,
        install                  BIGINT        NOT NULL DEFAULT 0,
        activation               BIGINT        NOT NULL DEFAULT 0 COMMENT '激活事件数（媒体口径）',
        registration             BIGINT        NOT NULL DEFAULT 0 COMMENT '注册事件数（媒体口径）',
        purchase                 BIGINT        NOT NULL DEFAULT 0 COMMENT '购买事件数（媒体口径）',

        -- ── Cohort UV（last-touch 归因）──────────────────────────
        cohort_activations       BIGINT        NOT NULL DEFAULT 0 COMMENT '激活 cohort 人数（uniq UV）',
        cohort_first_chargers    BIGINT        NOT NULL DEFAULT 0 COMMENT '120 天窗口内首充用户数',
        cohort_pay_users         BIGINT        NOT NULL DEFAULT 0 COMMENT '120 天窗口内付费用户数',

        -- ── 订阅 / 内购订单（金额单位 USD，已从美分转换）──────────
        first_sub_count          BIGINT        NOT NULL DEFAULT 0 COMMENT '首次订阅订单数',
        first_sub_amount         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '首次订阅金额 USD',
        renew_sub_count          BIGINT        NOT NULL DEFAULT 0 COMMENT '订阅续费订单数',
        renew_sub_amount         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '订阅续费金额 USD',
        first_iap_count          BIGINT        NOT NULL DEFAULT 0 COMMENT '首次内购订单数',
        first_iap_amount         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '首次内购金额 USD',
        repeat_iap_count         BIGINT        NOT NULL DEFAULT 0 COMMENT '复购内购订单数',
        repeat_iap_amount        DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '复购内购金额 USD',

        -- ── 累计充值（cohort N 日窗口）─────────────────────────
        total_recharge_amount    DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '该 cohort 全周期累计付费金额 USD',
        cum_recharge_1d          DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0 累计 USD',
        cum_recharge_3d          DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D2 累计 USD',
        cum_recharge_7d          DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D6 累计 USD',
        cum_recharge_14d         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D13 累计 USD',
        cum_recharge_30d         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D29 累计 USD',
        cum_recharge_90d         DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D89 累计 USD',
        cum_recharge_120d        DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT 'D0~D119 累计 USD',

        -- ── 元信息 ──────────────────────────────────────────────
        upstream_updated_at      DATETIME      DEFAULT NULL COMMENT '上游 INSERT OVERWRITE 时间 UTC',
        synced_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_ad_dsla (platform, ad_id, ds_la),
        INDEX idx_ds_account_local (ds_account_local),
        INDEX idx_ds_la (ds_la),
        INDEX idx_account_dsal (account_id, ds_account_local),
        INDEX idx_campaign_dsal (campaign_id, ds_account_local),
        INDEX idx_adgroup_dsal (adgroup_id, ds_account_local),
        INDEX idx_content_dsal (content_id, ds_account_local)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='投放归因日报（来源 metis.ads_ad_delivery_di / metis_dw.ads_ad_delivery_di）'
    """,
    # ─── 当日实时归因（来自 ODS 小时级 + DWD 充值事实，30 分钟刷新窗口）──────
    # 设计要点：
    # 1) 主源 ods_media_report_data_hi（spend/imp/click/activation/registration/purchase 等媒体口径），
    #    按 (platform, advertiser_id, ad_id, stat_time_day) argMax(updated_at_ms) 去重得到"截止当前最新"
    # 2) 辅源 dwd_invest_recharge_df（first_inapp / first_subscribe 标记 + 美分金额），
    #    按 (ad_id, pay_time→stat_time_day) 聚合，与主源 LEFT JOIN
    # 3) spend 保留账户原币种原值（保留 currency 列），未来加汇率表再做 USD 换算；
    #    充值金额（来自 dwd_invest_recharge_df）已经在统一口径，仍按"美分 / 100"转 USD
    # 4) 与 biz_attribution_ad_daily 的关系：本表覆盖"今天/昨天"小时级实时窗口，
    #    daily 表覆盖 T+1 cohort 完整窗口；前端"今天"用本表，"历史"用 daily 表
    """
    CREATE TABLE IF NOT EXISTS biz_attribution_ad_intraday (
        id                       BIGINT AUTO_INCREMENT PRIMARY KEY,

        -- ── 时间 / 时区 / 币种 ──────────────────────────────────────
        ds_account_local         DATE          NOT NULL COMMENT '账户日 = ods.stat_time_day（账户 timezone 下）',
        ds_la                    DATE          NOT NULL COMMENT 'LA 日（账户都是 LA/Phoenix 时近似等于 ds_account_local）',
        account_timezone         VARCHAR(64)   NOT NULL DEFAULT '',
        currency                 VARCHAR(8)    NOT NULL DEFAULT '' COMMENT '账户币种 USD / CNY / ...',

        -- ── 维度 ────────────────────────────────────────────────────
        platform                 VARCHAR(20)   NOT NULL COMMENT 'tiktok / facebook / google / ...',
        account_id               VARCHAR(100)  NOT NULL COMMENT '= ods.advertiser_id',
        ad_id                    VARCHAR(100)  NOT NULL,
        country                  VARCHAR(8)    NOT NULL DEFAULT '',

        -- ── 投放原子指标（来自 ods_media_report_data_hi，账户原币种原值）──
        spend                    DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '账户原币种原值，未做汇率换算',
        impressions              BIGINT        NOT NULL DEFAULT 0,
        clicks                   BIGINT        NOT NULL DEFAULT 0,
        inline_link_clicks       BIGINT        NOT NULL DEFAULT 0,
        reach                    BIGINT        NOT NULL DEFAULT 0,
        landing_page_view        BIGINT        NOT NULL DEFAULT 0,
        conversion               BIGINT        NOT NULL DEFAULT 0,
        install                  BIGINT        NOT NULL DEFAULT 0,
        activation               BIGINT        NOT NULL DEFAULT 0 COMMENT '媒体口径事件次数',
        registration             BIGINT        NOT NULL DEFAULT 0 COMMENT '媒体口径事件次数',
        purchase                 BIGINT        NOT NULL DEFAULT 0 COMMENT '媒体口径首充数（事件次数）',
        video_play_actions       BIGINT        NOT NULL DEFAULT 0,

        -- ── 业务归因充值（来自 dwd_invest_recharge_df，金额单位 USD）─
        first_iap_count          BIGINT        NOT NULL DEFAULT 0 COMMENT 'order_type=purchase AND first_inapp=1',
        first_iap_amount         DECIMAL(14,4) NOT NULL DEFAULT 0,
        first_sub_count          BIGINT        NOT NULL DEFAULT 0 COMMENT 'order_type=subscribe AND first_subscribe=1',
        first_sub_amount         DECIMAL(14,4) NOT NULL DEFAULT 0,
        total_recharge_amount    DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '当日归因到该 ad_id 的所有充值',

        -- ── 元信息 ──────────────────────────────────────────────────
        upstream_max_updated_at_ms BIGINT      NOT NULL DEFAULT 0 COMMENT 'ods 侧 MAX(updated_at_ms)，刷新版本号',
        synced_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_ad_dsacc (platform, ad_id, ds_account_local),
        INDEX idx_ds_la (ds_la),
        INDEX idx_account_dsal (account_id, ds_account_local)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='当日实时归因（来源 ods_media_report_data_hi + dwd_invest_recharge_df，30min 刷新）'
    """,
    """
    CREATE TABLE IF NOT EXISTS tiktok_material_uploads (
        id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
        advertiser_id       VARCHAR(100)  NOT NULL COMMENT 'TikTok 广告主 ID',
        local_file_name     VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '原始文件名',
        file_size_bytes     BIGINT        NOT NULL DEFAULT 0,
        duration_sec        DECIMAL(10,2) DEFAULT NULL COMMENT '视频时长（秒）',
        upload_channel      VARCHAR(20)   NOT NULL DEFAULT 'api' COMMENT 'manual / api',
        tiktok_video_id     VARCHAR(200)  DEFAULT NULL COMMENT 'TikTok 返回的 video_id',
        tiktok_file_name    VARCHAR(500)  DEFAULT NULL COMMENT 'TikTok 侧文件名',
        tiktok_url          TEXT          DEFAULT NULL COMMENT 'TikTok 素材预览 URL',
        tiktok_width        INT           DEFAULT NULL,
        tiktok_height       INT           DEFAULT NULL,
        tiktok_format       VARCHAR(20)   DEFAULT NULL,
        upload_status       VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT 'pending/uploading/success/failed',
        error_code          VARCHAR(50)   DEFAULT NULL,
        error_message       TEXT          DEFAULT NULL,
        can_use_for_ad      TINYINT       NOT NULL DEFAULT 0 COMMENT '是否可直接用于广告投放',
        ad_usage_note       VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '投放适用性说明',
        created_by          VARCHAR(100)  NOT NULL DEFAULT '',
        created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_advertiser (advertiser_id),
        INDEX idx_status (upload_status),
        INDEX idx_created (created_at DESC)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='TikTok 素材 API 上传记录'
    """,
    """
    -- 运营面板付费侧 PolarDB 影子表（与 biz_ops_daily 同 schema，仅含 os_type=1/2 行）
    -- 用途：双轨对账期，由 sync_ops_polardb_daily 写入；前端可通过 ?source=polardb 查询
    -- T+1 全量回填 30 天，与 biz_ops_daily 的 dwd 路径对账，确认偏差稳定后切主源
    CREATE TABLE IF NOT EXISTS biz_ops_daily_polardb_shadow (
        id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
        ds                       DATE          NOT NULL COMMENT '统计日 LA',
        os_type                  TINYINT       NOT NULL COMMENT '1=Android / 2=iOS（不含 0 用户侧）',
        subscribe_revenue_usd    DECIMAL(14,4) NOT NULL DEFAULT 0,
        onetime_revenue_usd      DECIMAL(14,4) NOT NULL DEFAULT 0,
        first_sub_orders         BIGINT        NOT NULL DEFAULT 0,
        repeat_sub_orders        BIGINT        NOT NULL DEFAULT 0,
        first_iap_orders         BIGINT        NOT NULL DEFAULT 0,
        repeat_iap_orders        BIGINT        NOT NULL DEFAULT 0,
        payer_uv                 BIGINT        NOT NULL DEFAULT 0,
        synced_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ds_os (ds, os_type),
        INDEX idx_ds (ds)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='运营面板付费侧 PolarDB 影子表（双轨对账期专用，与 biz_ops_daily 同口径）'
    """,
    """
    -- 运营面板实时层：从 matrix_order.recharge_order 30 分钟刷新今日+昨日 LA 数据
    -- 用途：API 智能路由 — 今日/昨日 LA 读这张表，其余日期读 biz_ops_daily
    -- 由 sync_ops_polardb_intraday 任务写入；仅含 os_type=1/2 付费侧
    CREATE TABLE IF NOT EXISTS biz_ops_daily_intraday (
        id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
        ds                       DATE          NOT NULL COMMENT '统计日 LA（仅今日+昨日）',
        os_type                  TINYINT       NOT NULL COMMENT '1=Android / 2=iOS',
        subscribe_revenue_usd    DECIMAL(14,4) NOT NULL DEFAULT 0,
        onetime_revenue_usd      DECIMAL(14,4) NOT NULL DEFAULT 0,
        first_sub_orders         BIGINT        NOT NULL DEFAULT 0,
        repeat_sub_orders        BIGINT        NOT NULL DEFAULT 0,
        first_iap_orders         BIGINT        NOT NULL DEFAULT 0,
        repeat_iap_orders        BIGINT        NOT NULL DEFAULT 0,
        payer_uv                 BIGINT        NOT NULL DEFAULT 0,
        upstream_max_id          BIGINT        NOT NULL DEFAULT 0 COMMENT '上游 recharge_order.id 最大值（版本号）',
        synced_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ds_os (ds, os_type),
        INDEX idx_ds (ds)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='运营面板付费侧实时层（仅含今日+昨日 LA，30min 覆盖刷新，来源 matrix_order.recharge_order）'
    """,
    """
    -- 运营数据面板日报：从 MaxCompute metis_dw 同步
    --   os_type=0 行：用户侧全量指标（注册/激活/DAU/留存）— 来自 ads_app_di
    --   os_type=1/2 行：付费侧双端拆分指标（金额/订单数/付费UV）— 来自 dwd_recharge_order_df
    -- 同步任务：tasks/sync_ops_daily.py，每日 03:00 LA 执行，回填 30 天
    CREATE TABLE IF NOT EXISTS biz_ops_daily (
        id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
        ds                       DATE          NOT NULL COMMENT '统计日 LA',
        os_type                  TINYINT       NOT NULL COMMENT '0=全量(用户侧) / 1=Android / 2=iOS',

        -- 用户侧（仅 os_type=0 行有值）
        new_register_uv          BIGINT        NOT NULL DEFAULT 0 COMMENT '新注册账号 UV (register_time_utc 转 LA = ds)',
        new_active_uv            BIGINT        NOT NULL DEFAULT 0 COMMENT '新激活 UV (App 首次启动)',
        active_uv                BIGINT        NOT NULL DEFAULT 0 COMMENT 'DAU',
        d1_retained_uv           BIGINT        NOT NULL DEFAULT 0,
        d7_retained_uv           BIGINT        NOT NULL DEFAULT 0,
        d30_retained_uv          BIGINT        NOT NULL DEFAULT 0,
        total_payer_uv           BIGINT        NOT NULL DEFAULT 0 COMMENT '当日充值付费 UV (来自 ads_app_di.recharge_pay_uv，全量不拆 OS)',

        -- 付费侧（仅 os_type=1/2 行有值，单位 USD 已从美分换算）
        subscribe_revenue_usd    DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '订阅充值金额 USD',
        onetime_revenue_usd      DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '内购充值金额 USD',
        first_sub_orders         BIGINT        NOT NULL DEFAULT 0 COMMENT '首次订阅订单数',
        repeat_sub_orders        BIGINT        NOT NULL DEFAULT 0 COMMENT '续订订单数',
        first_iap_orders         BIGINT        NOT NULL DEFAULT 0 COMMENT '首次内购订单数',
        repeat_iap_orders        BIGINT        NOT NULL DEFAULT 0 COMMENT '复购内购订单数',
        payer_uv                 BIGINT        NOT NULL DEFAULT 0 COMMENT '该 OS 当日付费 UV',

        -- 投放侧（仅 os_type=0 行有值，全平台合计；单位 USD）
        ad_spend_usd             DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '当日广告消耗 USD（全量平台合计，来自 biz_attribution_ad_daily）',

        synced_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        UNIQUE KEY uk_ds_os (ds, os_type),
        INDEX idx_ds (ds)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='运营数据面板日报：os_type=0 全量用户侧 + os_type=1/2 双端付费侧'
    """,
]


def init_biz_tables():
    """在业务库中创建数据沉淀表(幂等)。启动时调用。"""
    settings = get_settings()
    if not settings.biz_mysql_database:
        logger.info("init_biz_tables: BIZ_MYSQL_DATABASE 未配置，跳过")
        return
    try:
        conn = _create_biz_conn()
    except Exception as e:
        logger.warning(f"init_biz_tables: BIZ 业务库连接失败，跳过建表: {e}")
        return
    try:
        cur = conn.cursor()
        for sql in _BIZ_TABLES_SQL:
            cur.execute(sql)
        _migrate_biz_ad_accounts_columns(cur)
        _migrate_returned_conversion_d0_columns(cur)
        _migrate_returned_conversion_cleanup(cur)
        _migrate_optimizer_mapping_columns(cur)
        _migrate_biz_ops_daily_ad_spend(cur)
        conn.commit()
        logger.info("BIZ 业务库数据沉淀表初始化完成")
    except Exception as e:
        logger.error(f"init_biz_tables 失败: {e}")
    finally:
        conn.close()


def _migrate_biz_ops_daily_ad_spend(cur):
    """幂等：为既有 biz_ops_daily 表补 ad_spend_usd 列。

    新建表时 _BIZ_TABLES_SQL 已经包含此列；本函数仅处理"先建表再加列"场景。
    """
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'biz_ops_daily'"
    )
    cols = {r["COLUMN_NAME"] for r in cur.fetchall()}
    if not cols:
        return  # 表还没建出来（首次启动），跳过
    if "ad_spend_usd" not in cols:
        cur.execute(
            "ALTER TABLE biz_ops_daily "
            "ADD COLUMN ad_spend_usd DECIMAL(14,4) NOT NULL DEFAULT 0 "
            "COMMENT '当日广告消耗 USD（全量平台合计）' AFTER payer_uv"
        )
        logger.info("biz_ops_daily 已补字段 ad_spend_usd")


def _migrate_optimizer_mapping_columns(cur):
    """为 campaign_optimizer_mapping 补齐 match_source / match_confidence / match_position 列（幂等）"""
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'campaign_optimizer_mapping'")
    existing = {r["COLUMN_NAME"] for r in cur.fetchall()}
    migrations = [
        ("optimizer_match_source",
         "ADD COLUMN optimizer_match_source VARCHAR(50) NOT NULL DEFAULT 'campaign_name' "
         "COMMENT '匹配来源: structured_field/campaign_name/historical_mapping/default_rule/unassigned' "
         "AFTER parse_error"),
        ("optimizer_match_confidence",
         "ADD COLUMN optimizer_match_confidence DECIMAL(4,2) NOT NULL DEFAULT 0.90 "
         "COMMENT '匹配置信度 0~1' AFTER optimizer_match_source"),
        ("optimizer_match_position",
         "ADD COLUMN optimizer_match_position VARCHAR(20) NOT NULL DEFAULT '' "
         "COMMENT '匹配位置: field_6/field_11/field_12/unassigned' AFTER optimizer_match_confidence"),
    ]
    for col, ddl in migrations:
        if col not in existing:
            cur.execute(f"ALTER TABLE campaign_optimizer_mapping {ddl}")


def _migrate_returned_conversion_d0_columns(cur):
    """为 ad_returned_conversion_daily 补齐 D0 Cohort + 计数列（幂等）"""
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ad_returned_conversion_daily'")
    existing = {r["COLUMN_NAME"] for r in cur.fetchall()}
    migrations = [
        ("d0_registrations_returned",   "ADD COLUMN d0_registrations_returned   BIGINT        NOT NULL DEFAULT 0 COMMENT '首日注册数（D0 cohort）' AFTER d1_roi_returned"),
        ("d0_purchase_value_returned",  "ADD COLUMN d0_purchase_value_returned  DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '首日充值金额（D0 cohort）' AFTER d0_registrations_returned"),
        ("d0_subscribe_value_returned", "ADD COLUMN d0_subscribe_value_returned DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '首日订阅金额（D0 cohort）' AFTER d0_purchase_value_returned"),
        ("purchase_count_returned",     "ADD COLUMN purchase_count_returned     BIGINT        NOT NULL DEFAULT 0 COMMENT '回传内购数/购买次数（平台归因）' AFTER purchase_value_returned"),
        ("subscribe_count_returned",    "ADD COLUMN subscribe_count_returned    BIGINT        NOT NULL DEFAULT 0 COMMENT '回传订阅数/订阅次数（平台归因，不支持时为0）' AFTER subscribe_value_returned"),
    ]
    for col, ddl in migrations:
        if col not in existing:
            cur.execute(f"ALTER TABLE ad_returned_conversion_daily {ddl}")


def _migrate_returned_conversion_cleanup(cur):
    """清理 ad_returned_conversion_daily 中因 NULL 唯一键失效产生的重复行 + campaign/adset 汇总行（幂等）。

    问题根因：
      1. upsert() 将空字符串转为 NULL → 唯一键无法去重 → 每次同步都 INSERT 新行
      2. campaign/adset/ad 三级同时写入 → 同一笔花费被 SUM 3 次
    修复策略：
      Step 1: 先删除"NULL 等价重复行"（把 NULL 视为 '' 后与其他行重复的行，只保留 id 最大的）
      Step 2: 将唯一键列中的 NULL 统一为空字符串
      Step 3: 删除转换后仍然存在的重复行
      Step 4: 删除 campaign/adset 汇总行
    """
    cur.execute("SELECT COUNT(*) AS cnt FROM ad_returned_conversion_daily")
    total = cur.fetchone()["cnt"]
    if total == 0:
        return

    # Step 1: 删除"NULL 等价重复行"：将 NULL 视为 '' 后分组，每组只保留 id 最大的
    cur.execute("""
        DELETE t1 FROM ad_returned_conversion_daily t1
        INNER JOIN (
            SELECT COALESCE(stat_date, '1970-01-01') AS g_date,
                   COALESCE(media_source, '') AS g_ms,
                   COALESCE(account_id, '') AS g_acc,
                   COALESCE(campaign_id, '') AS g_cid,
                   COALESCE(adset_id, '') AS g_asid,
                   COALESCE(ad_id, '') AS g_adid,
                   COALESCE(country, '') AS g_co,
                   COALESCE(platform, '') AS g_pf,
                   MAX(id) AS keep_id
            FROM ad_returned_conversion_daily
            GROUP BY g_date, g_ms, g_acc, g_cid, g_asid, g_adid, g_co, g_pf
            HAVING COUNT(*) > 1
        ) t2 ON COALESCE(t1.stat_date, '1970-01-01') = t2.g_date
            AND COALESCE(t1.media_source, '') = t2.g_ms
            AND COALESCE(t1.account_id, '') = t2.g_acc
            AND COALESCE(t1.campaign_id, '') = t2.g_cid
            AND COALESCE(t1.adset_id, '') = t2.g_asid
            AND COALESCE(t1.ad_id, '') = t2.g_adid
            AND COALESCE(t1.country, '') = t2.g_co
            AND COALESCE(t1.platform, '') = t2.g_pf
            AND t1.id != t2.keep_id
    """)
    dedup_deleted = cur.rowcount
    if dedup_deleted > 0:
        logger.info(f"returned_conversion 清理: 删除 {dedup_deleted} 条唯一键重复行")

    # Step 2: NULL → 空字符串（让唯一键可以正常工作）
    for col in ("account_id", "campaign_id", "adset_id", "ad_id", "country", "platform"):
        cur.execute(f"UPDATE ad_returned_conversion_daily SET {col} = '' WHERE {col} IS NULL")

    # Step 3: 删除 campaign 汇总行（adset_id='' AND ad_id=''），前提是同 campaign 下存在 ad 级别行
    cur.execute("""
        DELETE FROM ad_returned_conversion_daily
        WHERE adset_id = '' AND ad_id = ''
          AND campaign_id IN (
              SELECT DISTINCT campaign_id FROM (
                  SELECT campaign_id FROM ad_returned_conversion_daily WHERE ad_id != ''
              ) sub
          )
    """)
    campaign_deleted = cur.rowcount

    # Step 4: 删除 adset 汇总行（ad_id=''），前提是同 adset 下存在 ad 级别行
    cur.execute("""
        DELETE FROM ad_returned_conversion_daily
        WHERE ad_id = '' AND adset_id != ''
          AND adset_id IN (
              SELECT DISTINCT adset_id FROM (
                  SELECT adset_id FROM ad_returned_conversion_daily WHERE ad_id != ''
              ) sub
          )
    """)
    adset_deleted = cur.rowcount

    if campaign_deleted + adset_deleted > 0:
        logger.info(f"returned_conversion 清理: 删除 {campaign_deleted} 条 campaign 汇总行, "
                    f"{adset_deleted} 条 adset 汇总行")

    cur.execute("SELECT COUNT(*) AS cnt FROM ad_returned_conversion_daily")
    remaining = cur.fetchone()["cnt"]
    logger.info(f"returned_conversion 清理完成: 清理前 {total} 行 → 清理后 {remaining} 行")


def _migrate_biz_ad_accounts_columns(cur):
    """为 biz_ad_accounts 表补齐新增列（幂等）"""
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'biz_ad_accounts'")
    existing = {r["COLUMN_NAME"] for r in cur.fetchall()}
    migrations = [
        ("access_token",   "ADD COLUMN access_token TEXT DEFAULT NULL AFTER status"),
        ("app_id",         "ADD COLUMN app_id VARCHAR(200) NOT NULL DEFAULT '' AFTER access_token"),
        ("app_secret",     "ADD COLUMN app_secret VARCHAR(200) NOT NULL DEFAULT '' AFTER app_id"),
        ("is_default",     "ADD COLUMN is_default TINYINT NOT NULL DEFAULT 0 AFTER app_secret"),
        ("last_synced_at", "ADD COLUMN last_synced_at DATETIME DEFAULT NULL AFTER is_default"),
    ]
    for col, ddl in migrations:
        if col not in existing:
            cur.execute(f"ALTER TABLE biz_ad_accounts {ddl}")
            logger.info(f"biz_ad_accounts: 已添加列 {col}")


def migrate_json_data():
    """将 JSON 文件中的历史数据一次性导入应用库（仅当目标表为空时执行）。"""
    try:
        conn = _create_app_conn()
    except Exception as e:
        logger.warning(f"migrate_json_data: APP 应用库连接失败，跳过迁移: {e}")
        return
    try:
        cur = conn.cursor()
        _migrate_users(cur, conn)
        _migrate_templates(cur, conn)
        _migrate_oplog(cur, conn)
    except Exception as e:
        logger.error(f"migrate_json_data 失败: {e}")
    finally:
        conn.close()


def _table_is_empty(cur, table: str) -> bool:
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
    return cur.fetchone()["cnt"] == 0


def _migrate_users(cur, conn):
    if not _table_is_empty(cur, "app_users"):
        return
    json_path = Path(__file__).parent / "users.json"
    if not json_path.exists():
        return
    try:
        users = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return
    count = 0
    for username, data in users.items():
        cur.execute(
            """INSERT INTO app_users (username, password_hash, role, display_name, assigned_accounts)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                data.get("username", username),
                data.get("hashed_password", ""),
                data.get("role", "optimizer"),
                data.get("display_name", username),
                json.dumps(data.get("assigned_accounts", []), ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    logger.info(f"已从 users.json 迁移 {count} 个用户到 APP.app_users")


def _migrate_app_templates_columns(cur):
    """为 app_templates 补齐系统母版相关列（幂等）。

    新增列：
      - template_key       : 系统母版唯一标识（如 tpl_tiktok_minis_basic）
      - is_system          : 是否系统母版（不可编辑/删除，但可另存为）
      - is_editable        : 是否允许直接编辑
      - parent_template_id : 自定义模板克隆来源
    """
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_templates'")
    existing = {r["COLUMN_NAME"] for r in cur.fetchall()}
    migrations = [
        ("template_key",
         "ADD COLUMN template_key VARCHAR(64) DEFAULT NULL COMMENT '系统母版唯一标识' AFTER tpl_id"),
        ("is_system",
         "ADD COLUMN is_system TINYINT NOT NULL DEFAULT 0 COMMENT '是否系统母版' AFTER is_builtin"),
        ("is_editable",
         "ADD COLUMN is_editable TINYINT NOT NULL DEFAULT 1 COMMENT '是否允许直接编辑' AFTER is_system"),
        ("parent_template_id",
         "ADD COLUMN parent_template_id VARCHAR(64) DEFAULT NULL COMMENT '克隆来源模板 tpl_id' AFTER is_editable"),
    ]
    for col, ddl in migrations:
        if col not in existing:
            cur.execute(f"ALTER TABLE app_templates {ddl}")
    # 索引（幂等：通过 INFORMATION_SCHEMA 查询是否存在）
    cur.execute("SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_templates'")
    idx_existing = {r["INDEX_NAME"] for r in cur.fetchall()}
    for idx_name, idx_ddl in [
        ("idx_template_key", "ADD INDEX idx_template_key (template_key)"),
        ("idx_is_system",    "ADD INDEX idx_is_system (is_system)"),
        ("idx_parent_tpl",   "ADD INDEX idx_parent_tpl (parent_template_id)"),
    ]:
        if idx_name not in idx_existing:
            try:
                cur.execute(f"ALTER TABLE app_templates {idx_ddl}")
            except Exception:
                pass


def _migrate_cbo_template_type_recovery(cur):
    """修复历史 bug：CBO 副本 template_type 被前端硬编码降级为 'web_to_app'（幂等）。

    判定降级证据 + 修复条件（必须同时满足，避免误伤正常 ABO 副本）：
      1. parent_template_id = 'tpl_meta_web_to_app_conv_cbo'（来源是 CBO 母版）
      2. content.template_type 当前 = 'web_to_app'（被改坏的特征）

    修复动作：
      - content.template_type    → 'web_to_app_conversion_cbo'
      - content.template_subtype → 'conversion_cbo'

    本迁移只动「来源 = CBO 母版」的副本，不会影响 ABO 母版的副本。
    """
    cur.execute(
        "SELECT id, content FROM app_templates "
        "WHERE parent_template_id = 'tpl_meta_web_to_app_conv_cbo'"
    )
    rows = cur.fetchall() or []
    if not rows:
        return
    patched = 0
    for r in rows:
        raw = r.get("content")
        try:
            c = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        if c.get("template_type") != "web_to_app":
            continue  # 已正确 / 不在修复范围
        c["template_type"] = "web_to_app_conversion_cbo"
        c["template_subtype"] = "conversion_cbo"
        cur.execute(
            "UPDATE app_templates SET content = %s WHERE id = %s",
            (json.dumps(c, ensure_ascii=False), r["id"]),
        )
        patched += 1
    if patched:
        logger.info(f"CBO 模板 template_type 降级修复: 已恢复 {patched} 条副本为 CBO 类型")


def _migrate_app_templates_delivery_language(cur):
    """为所有 app_templates 行的 content 补齐 delivery_languages / default_delivery_language（幂等）。

    旧记录默认 ["en"] / "en"；不影响已有字段。
    """
    cur.execute("SELECT id, content FROM app_templates")
    rows = cur.fetchall() or []
    patched = 0
    for r in rows:
        raw = r.get("content")
        try:
            c = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            c = {}
        if not isinstance(c, dict):
            continue
        langs = c.get("delivery_languages")
        default_lang = c.get("default_delivery_language")
        valid_langs = (
            isinstance(langs, list) and bool(langs)
            and all(isinstance(x, str) and x.strip() for x in langs)
        )
        if not valid_langs:
            c["delivery_languages"] = ["en"]
            valid_langs = True
        if not isinstance(default_lang, str) or default_lang not in c["delivery_languages"]:
            c["default_delivery_language"] = c["delivery_languages"][0]
        if (langs == c.get("delivery_languages")
                and default_lang == c.get("default_delivery_language")):
            continue
        cur.execute(
            "UPDATE app_templates SET content = %s WHERE id = %s",
            (json.dumps(c, ensure_ascii=False), r["id"]),
        )
        patched += 1
    if patched:
        logger.info(f"投放语种字段迁移: 已补齐 {patched} 条模板 content")


def _migrate_templates(cur, conn):
    from routes.templates import BUILTIN_TEMPLATES

    _migrate_app_templates_columns(cur)
    conn.commit()

    is_empty = _table_is_empty(cur, "app_templates")

    all_templates: list[dict] = []
    builtin_ids = {t["id"] for t in BUILTIN_TEMPLATES}

    for t in BUILTIN_TEMPLATES:
        all_templates.append(t)

    if is_empty:
        json_path = Path(__file__).parent / "templates.json"
        if json_path.exists():
            try:
                file_data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(file_data, list):
                    for t in file_data:
                        if isinstance(t, dict) and t.get("id"):
                            if t["id"] in builtin_ids:
                                for i, bt in enumerate(all_templates):
                                    if bt["id"] == t["id"]:
                                        all_templates[i] = t
                                        break
                            else:
                                all_templates.append(t)
            except Exception:
                pass

    inserted = 0
    updated = 0
    for t in all_templates:
        tpl_id = t.get("id", "")
        name = t.get("name", "")
        platform = t.get("platform", "tiktok")
        is_builtin = 1 if tpl_id in builtin_ids else 0
        is_system = 1 if t.get("is_system") else 0
        is_editable = 0 if (is_system and t.get("is_editable") is False) else (
            1 if t.get("is_editable", True) else 0
        )
        template_key = t.get("template_key") or None
        parent_template_id = t.get("parent_template_id") or None
        created_at = t.get("created_at")
        content = {k: v for k, v in t.items()
                   if k not in ("id", "name", "platform", "created_at", "updated_at",
                                "is_system", "is_editable", "template_key",
                                "parent_template_id", "is_builtin")}
        content_json = json.dumps(content, ensure_ascii=False)

        cur.execute("SELECT 1 FROM app_templates WHERE tpl_id = %s", (tpl_id,))
        if cur.fetchone():
            if tpl_id in builtin_ids:
                cur.execute(
                    """UPDATE app_templates
                          SET name = %s, platform = %s, content = %s,
                              is_builtin = 1,
                              is_system = %s,
                              is_editable = %s,
                              template_key = %s
                        WHERE tpl_id = %s""",
                    (name, platform, content_json,
                     is_system, is_editable, template_key, tpl_id),
                )
                updated += 1
            continue

        cur.execute(
            """INSERT INTO app_templates
                  (tpl_id, template_key, name, platform,
                   is_builtin, is_system, is_editable, parent_template_id,
                   content, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (tpl_id, template_key, name, platform,
             is_builtin, is_system, is_editable, parent_template_id,
             content_json,
             created_at or time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        inserted += 1
    if inserted or updated:
        conn.commit()
        logger.info(f"模板同步完成: 新增 {inserted}, 更新 {updated} 个内置模板到 APP.app_templates")

    # 在内置母版同步之后再补齐用户自建/历史模板的 delivery_languages 字段
    _migrate_app_templates_delivery_language(cur)
    # 修复历史 bug：把被前端硬编码降级为 'web_to_app' 的 CBO 副本拉回 CBO
    _migrate_cbo_template_type_recovery(cur)
    conn.commit()


def _migrate_oplog(cur, conn):
    if not _table_is_empty(cur, "app_oplog"):
        return
    json_path = Path(__file__).parent / "oplog.json"
    if not json_path.exists():
        return
    try:
        logs = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(logs, list):
        return
    count = 0
    for entry in logs:
        target_raw = entry.get("target", "")
        target_type = ""
        target_id = ""
        platform = ""
        if "TikTok" in target_raw:
            platform = "tiktok"
        elif "Meta" in target_raw:
            platform = "meta"
        if "广告系列" in target_raw:
            target_type = "campaign"
            nums = [p for p in target_raw.split() if p.isdigit()]
            target_id = nums[0] if nums else ""
        elif "广告组" in target_raw:
            target_type = "adgroup"
            nums = [p for p in target_raw.split() if p.isdigit()]
            target_id = nums[0] if nums else ""
        else:
            target_type = target_raw

        cur.execute(
            """INSERT INTO app_oplog (username, action, target_type, target_id, platform, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                entry.get("user", ""),
                entry.get("action", ""),
                target_type,
                target_id,
                platform,
                entry.get("time", time.strftime("%Y-%m-%d %H:%M:%S")),
            ),
        )
        count += 1
    conn.commit()
    logger.info(f"已从 oplog.json 迁移 {count} 条日志到 APP.app_oplog")
