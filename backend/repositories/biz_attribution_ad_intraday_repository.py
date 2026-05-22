"""当日实时归因数据访问层 — biz_attribution_ad_intraday (adpilot_biz)

数据来源：metis_dw.ods_media_report_data_hi（小时级媒体口径）+ dwd_invest_recharge_df（充值事实）
        → AdsMind 通过 sync_attribution_intraday 任务每 30 分钟刷新本表

口径要点：
- 时间维度只有 ds_account_local（账户日，= ods.stat_time_day）+ ds_la（账户都是 LA/Phoenix 时近似等价）
- spend 为账户原币种原值（保留 currency 列），未来加汇率表再做 USD 换算
- first_iap_amount / first_sub_amount / total_recharge_amount 已在 SQL 层从美分转 USD
- 不含 cohort 累计 / N 日 ROI（cohort 类指标看 daily 表）
"""
from __future__ import annotations

from typing import Any, Optional

from db import get_biz_conn

# ─────────────────────────────────────────────────────────────
#  常量 / 约束
# ─────────────────────────────────────────────────────────────

_TZ_BASIS_MAP = {
    "account_local": "ds_account_local",
    "la": "ds_la",
}

_ALLOWED_TOP_METRICS = {
    "spend", "impressions", "clicks", "registration", "purchase",
    "first_iap_amount", "first_iap_count",
    "first_sub_amount", "first_sub_count",
    "total_recharge_amount",
}

_AGG_GROUP_BY = {
    "ad":      ("platform", "account_id", "ad_id"),
    "account": ("platform", "account_id"),
}


def _resolve_tz_col(tz_basis: str) -> str:
    return _TZ_BASIS_MAP.get(tz_basis, "ds_account_local")


# ─────────────────────────────────────────────────────────────
#  写入
# ─────────────────────────────────────────────────────────────

_INSERT_COLUMNS = (
    "ds_account_local", "ds_la", "account_timezone", "currency",
    "platform", "account_id", "ad_id", "country",
    "spend", "impressions", "clicks", "inline_link_clicks", "reach",
    "landing_page_view", "conversion", "install",
    "activation", "registration", "purchase", "video_play_actions",
    "first_iap_count", "first_iap_amount",
    "first_sub_count", "first_sub_amount",
    "total_recharge_amount",
    "upstream_max_updated_at_ms",
)
_UPDATE_COLUMNS = tuple(c for c in _INSERT_COLUMNS if c not in ("ds_account_local", "platform", "ad_id"))


def upsert_batch(rows: list[dict]) -> int:
    """批量写入，主键冲突走 ON DUPLICATE KEY UPDATE"""
    if not rows:
        return 0
    cols_sql = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_INSERT_COLUMNS))
    update_sql = ", ".join(f"{c} = VALUES({c})" for c in _UPDATE_COLUMNS)
    # 命中现有行时也刷新 synced_at（DDL 里的 DEFAULT CURRENT_TIMESTAMP 仅 INSERT 生效）
    update_sql += ", synced_at = CURRENT_TIMESTAMP"
    sql = (
        f"INSERT INTO biz_attribution_ad_intraday ({cols_sql}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )
    params = [tuple(r.get(c) for c in _INSERT_COLUMNS) for r in rows]
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


def delete_window(start_date: str, end_date: str, *, tz_basis: str = "account_local") -> int:
    """删窗（极少用，主要用于全量回填前清场）"""
    col = _resolve_tz_col(tz_basis)
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM biz_attribution_ad_intraday WHERE {col} BETWEEN %s AND %s",
            (start_date, end_date),
        )
        conn.commit()
        return cur.rowcount


# ─────────────────────────────────────────────────────────────
#  查询：通用 WHERE 子句构造
# ─────────────────────────────────────────────────────────────

def _build_where(tz_col: str, start_date: str, end_date: str, *,
                 platform: Optional[str] = None,
                 account_id: Optional[str] = None,
                 ad_id: Optional[str] = None) -> tuple[str, list[Any]]:
    parts = [f"{tz_col} BETWEEN %s AND %s"]
    args: list[Any] = [start_date, end_date]
    if platform:
        parts.append("platform = %s")
        args.append(platform)
    if account_id:
        parts.append("account_id = %s")
        args.append(account_id)
    if ad_id:
        parts.append("ad_id = %s")
        args.append(ad_id)
    return "WHERE " + " AND ".join(parts), args


# ─────────────────────────────────────────────────────────────
#  查询：data_range / overview / daily / top
# ─────────────────────────────────────────────────────────────

def get_data_range() -> dict:
    """返回 ds_account_local 覆盖范围 + 上游最新版本时间，前端默认区间 / 同步状态用"""
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MIN(ds_account_local) AS min_ds_account_local, "
            "MAX(ds_account_local) AS max_ds_account_local, "
            "MIN(ds_la) AS min_ds_la, MAX(ds_la) AS max_ds_la, "
            "COUNT(*) AS row_cnt, "
            "MAX(upstream_max_updated_at_ms) AS upstream_max_updated_at_ms, "
            "MAX(synced_at) AS last_synced_at "
            "FROM biz_attribution_ad_intraday"
        )
        return cur.fetchone() or {}


_OVERVIEW_SQL = """
SELECT
    COALESCE(SUM(spend), 0)                  AS total_spend,
    COALESCE(SUM(impressions), 0)            AS total_impressions,
    COALESCE(SUM(clicks), 0)                 AS total_clicks,
    COALESCE(SUM(inline_link_clicks), 0)     AS total_inline_link_clicks,
    COALESCE(SUM(reach), 0)                  AS total_reach,
    COALESCE(SUM(landing_page_view), 0)      AS total_landing_page_view,
    COALESCE(SUM(conversion), 0)             AS total_conversion,
    COALESCE(SUM(install), 0)                AS total_install,
    COALESCE(SUM(activation), 0)             AS total_activation,
    COALESCE(SUM(registration), 0)           AS total_registration,
    COALESCE(SUM(purchase), 0)               AS total_purchase,
    COALESCE(SUM(first_iap_count), 0)        AS total_first_iap_count,
    COALESCE(SUM(first_iap_amount), 0)       AS total_first_iap_amount,
    COALESCE(SUM(first_sub_count), 0)        AS total_first_sub_count,
    COALESCE(SUM(first_sub_amount), 0)       AS total_first_sub_amount,
    COALESCE(SUM(total_recharge_amount), 0)  AS total_recharge_amount,
    CASE WHEN SUM(spend) > 0
         THEN ROUND(SUM(total_recharge_amount) / SUM(spend), 6)
         ELSE NULL END                       AS roi_intraday,
    COUNT(DISTINCT platform)                 AS n_platform,
    COUNT(DISTINCT account_id)               AS n_account,
    COUNT(DISTINCT ad_id)                    AS n_ad
FROM biz_attribution_ad_intraday
"""


def get_overview(start_date: str, end_date: str, *,
                 tz_basis: str = "account_local",
                 platform: Optional[str] = None,
                 account_id: Optional[str] = None,
                 ad_id: Optional[str] = None) -> dict:
    tz_col = _resolve_tz_col(tz_basis)
    where, args = _build_where(tz_col, start_date, end_date,
                                platform=platform, account_id=account_id, ad_id=ad_id)
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(_OVERVIEW_SQL + " " + where, args)
        return cur.fetchone() or {}


def get_daily_trend(start_date: str, end_date: str, *,
                    tz_basis: str = "account_local",
                    platform: Optional[str] = None,
                    account_id: Optional[str] = None,
                    ad_id: Optional[str] = None) -> list[dict]:
    """按 ds_account_local 或 ds_la 聚合的日级趋势"""
    tz_col = _resolve_tz_col(tz_basis)
    where, args = _build_where(tz_col, start_date, end_date,
                                platform=platform, account_id=account_id, ad_id=ad_id)
    sql = (
        f"SELECT {tz_col} AS ds, "
        "COALESCE(SUM(spend), 0)                  AS spend, "
        "COALESCE(SUM(impressions), 0)            AS impressions, "
        "COALESCE(SUM(clicks), 0)                 AS clicks, "
        "COALESCE(SUM(registration), 0)           AS registration, "
        "COALESCE(SUM(purchase), 0)               AS purchase, "
        "COALESCE(SUM(first_iap_count), 0)        AS first_iap_count, "
        "COALESCE(SUM(first_iap_amount), 0)       AS first_iap_amount, "
        "COALESCE(SUM(first_sub_count), 0)        AS first_sub_count, "
        "COALESCE(SUM(first_sub_amount), 0)       AS first_sub_amount, "
        "COALESCE(SUM(total_recharge_amount), 0)  AS total_recharge_amount, "
        "CASE WHEN SUM(spend) > 0 "
        "     THEN ROUND(SUM(total_recharge_amount) / SUM(spend), 6) "
        "     ELSE NULL END                       AS roi_intraday, "
        "COUNT(DISTINCT ad_id)                    AS n_ad "
        f"FROM biz_attribution_ad_intraday {where} "
        f"GROUP BY {tz_col} ORDER BY {tz_col}"
    )
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        return cur.fetchall() or []


def sum_spend_by_ds_la(start_date: str, end_date: str) -> dict[str, float]:
    """按 ds_la 聚合 SUM(spend)，返回 {YYYY-MM-DD: spend_usd}。

    用途：当 T+1 cohort 表 biz_attribution_ad_daily 还没落到某天的分区时，
    运营面板/任何按 LA 日聚合 spend 的场景可以用本函数实时兜底。
    spend 已是 USD 浮点（同步层已换算），但精度/口径与 daily 表会有微小差异，
    因此 daily 有值时不应被本函数覆盖。
    """
    out: dict[str, float] = {}
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ds_la, SUM(spend) AS spend FROM biz_attribution_ad_intraday "
            "WHERE ds_la BETWEEN %s AND %s GROUP BY ds_la",
            (start_date, end_date),
        )
        for row in cur.fetchall():
            ds = row.get("ds_la")
            ds_str = ds.strftime("%Y-%m-%d") if hasattr(ds, "strftime") else str(ds)[:10]
            try:
                out[ds_str] = round(float(row.get("spend") or 0), 4)
            except (TypeError, ValueError):
                out[ds_str] = 0.0
    return out


def get_aggregated(start_date: str, end_date: str, *,
                   group_by: str = "ad",
                   tz_basis: str = "account_local",
                   platform: Optional[str] = None,
                   account_id: Optional[str] = None,
                   limit: int = 200,
                   offset: int = 0,
                   order_by: str = "spend",
                   order_dir: str = "DESC") -> list[dict]:
    """按 ad / account 维度聚合，分页返回"""
    if group_by not in _AGG_GROUP_BY:
        raise ValueError(f"group_by 必须是 {list(_AGG_GROUP_BY.keys())}")
    if order_by not in _ALLOWED_TOP_METRICS:
        raise ValueError(f"order_by 必须是 {sorted(_ALLOWED_TOP_METRICS)}")
    if order_dir.upper() not in ("ASC", "DESC"):
        raise ValueError("order_dir 必须是 ASC / DESC")

    tz_col = _resolve_tz_col(tz_basis)
    group_cols = ", ".join(_AGG_GROUP_BY[group_by])
    where, args = _build_where(tz_col, start_date, end_date,
                                platform=platform, account_id=account_id)

    sql = (
        f"SELECT {group_cols}, "
        "COALESCE(SUM(spend), 0)                  AS spend, "
        "COALESCE(SUM(impressions), 0)            AS impressions, "
        "COALESCE(SUM(clicks), 0)                 AS clicks, "
        "COALESCE(SUM(registration), 0)           AS registration, "
        "COALESCE(SUM(purchase), 0)               AS purchase, "
        "COALESCE(SUM(first_iap_count), 0)        AS first_iap_count, "
        "COALESCE(SUM(first_iap_amount), 0)       AS first_iap_amount, "
        "COALESCE(SUM(first_sub_count), 0)        AS first_sub_count, "
        "COALESCE(SUM(first_sub_amount), 0)       AS first_sub_amount, "
        "COALESCE(SUM(total_recharge_amount), 0)  AS total_recharge_amount, "
        "CASE WHEN SUM(spend) > 0 "
        "     THEN ROUND(SUM(total_recharge_amount) / SUM(spend), 6) "
        "     ELSE NULL END                       AS roi_intraday "
        f"FROM biz_attribution_ad_intraday {where} "
        f"GROUP BY {group_cols} "
        f"ORDER BY {order_by} {order_dir.upper()} "
        f"LIMIT %s OFFSET %s"
    )
    args = args + [int(limit), int(offset)]
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        return cur.fetchall() or []


def get_top_ads(start_date: str, end_date: str, *,
                metric: str = "spend",
                limit: int = 10,
                tz_basis: str = "account_local",
                platform: Optional[str] = None,
                account_id: Optional[str] = None) -> list[dict]:
    """按指定指标 Top N 广告 (ad_id 维度)"""
    if metric not in _ALLOWED_TOP_METRICS:
        raise ValueError(f"metric 必须是 {sorted(_ALLOWED_TOP_METRICS)}")
    return get_aggregated(start_date, end_date,
                          group_by="ad", tz_basis=tz_basis,
                          platform=platform, account_id=account_id,
                          limit=limit, offset=0,
                          order_by=metric, order_dir="DESC")
