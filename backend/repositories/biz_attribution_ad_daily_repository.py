"""归因日报数据访问层 — biz_attribution_ad_daily (adpilot_biz)

数据来源：metis_dw.ads_ad_delivery_di（MaxCompute）→ 同步到 ClickHouse 的 metis.ads_ad_delivery_di
        → AdsMind 通过 sync_attribution_daily 任务从 CK 拉到本表

口径要点：
- 金额已在同步层从美分转 USD（DECIMAL(14,4)）
- ds_la = 上游 LA cohort 日；ds_account_local = 按账户时区近似（LA + Phoenix 当前等于 ds_la）
- ROI / N 日 ROI 在 SQL 层动态算，不预存
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

_ALLOWED_GROUP_BY = {
    "ad": ("platform", "account_id", "campaign_id", "campaign_name",
           "adgroup_id", "adgroup_name", "ad_id", "ad_name"),
    "adgroup": ("platform", "account_id", "campaign_id", "campaign_name",
                "adgroup_id", "adgroup_name"),
    "campaign": ("platform", "account_id", "campaign_id", "campaign_name"),
    "account": ("platform", "account_id", "account_name"),
}

_ALLOWED_DAILY_ORDER = {
    "ds", "spend", "impressions", "clicks", "registration", "install",
    "activation", "purchase", "first_iap_amount", "first_sub_amount",
    "total_recharge_amount", "cum_recharge_1d", "cum_recharge_7d",
    "cum_recharge_30d", "cum_recharge_90d", "cum_recharge_120d",
    "first_iap_count", "first_sub_count", "ad_name", "campaign_name",
}

_ALLOWED_TOP_METRICS = {
    "spend", "registration", "install", "activation", "purchase",
    "first_iap_amount", "first_iap_count",
    "first_sub_amount", "first_sub_count",
    "renew_sub_amount", "renew_sub_count",
    "repeat_iap_amount", "repeat_iap_count",
    "total_recharge_amount", "cum_recharge_1d", "cum_recharge_3d",
    "cum_recharge_7d", "cum_recharge_14d", "cum_recharge_30d",
    "cum_recharge_90d", "cum_recharge_120d",
    "roi_1d", "roi_3d", "roi_7d", "roi_14d", "roi_30d", "roi_90d", "roi_120d",
}


def _resolve_tz_col(tz_basis: str) -> str:
    return _TZ_BASIS_MAP.get(tz_basis, "ds_account_local")


# ─────────────────────────────────────────────────────────────
#  写入
# ─────────────────────────────────────────────────────────────

_INSERT_COLUMNS = (
    "ds_la", "ds_account_local", "account_timezone", "timezone_source",
    "platform", "account_id", "account_name", "account_status",
    "campaign_id", "campaign_name", "delivery_method", "operator_id",
    "content_id", "objective_type", "budget_mode", "budget_amount",
    "adgroup_id", "adgroup_name", "optimize_goal", "bid_type",
    "ad_id", "ad_name", "creative_id", "video_id", "ad_status",
    "spend", "impressions", "clicks", "inline_link_clicks",
    "landing_page_view", "conversion", "install", "activation",
    "registration", "purchase",
    "cohort_activations", "cohort_first_chargers", "cohort_pay_users",
    "first_sub_count", "first_sub_amount", "renew_sub_count", "renew_sub_amount",
    "first_iap_count", "first_iap_amount", "repeat_iap_count", "repeat_iap_amount",
    "total_recharge_amount",
    "cum_recharge_1d", "cum_recharge_3d", "cum_recharge_7d", "cum_recharge_14d",
    "cum_recharge_30d", "cum_recharge_90d", "cum_recharge_120d",
    "upstream_updated_at",
)

_UPDATE_COLUMNS = tuple(c for c in _INSERT_COLUMNS if c not in ("ds_la", "platform", "ad_id"))


def upsert_batch(rows: list[dict]) -> int:
    """批量 upsert，rows 每个 dict 必须含 _INSERT_COLUMNS 中的字段（缺省按默认值处理）"""
    if not rows:
        return 0

    cols_sql = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_INSERT_COLUMNS))
    update_sql = ", ".join(f"{c} = VALUES({c})" for c in _UPDATE_COLUMNS)
    # 命中现有行时也刷新 synced_at（DDL 里的 DEFAULT CURRENT_TIMESTAMP 仅 INSERT 生效）
    update_sql += ", synced_at = CURRENT_TIMESTAMP"
    sql = (
        f"INSERT INTO biz_attribution_ad_daily ({cols_sql}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )

    params = [tuple(r.get(c) for c in _INSERT_COLUMNS) for r in rows]
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


def delete_window(start_ds: str, end_ds: str, tz_basis: str = "la") -> int:
    """按 ds_la（默认）或 ds_account_local 删除一段窗口数据，用于全量回刷模式"""
    col = _resolve_tz_col(tz_basis if tz_basis == "account_local" else "la")
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM biz_attribution_ad_daily WHERE {col} BETWEEN %s AND %s",
            (start_ds, end_ds),
        )
        conn.commit()
        return cur.rowcount


# ─────────────────────────────────────────────────────────────
#  通用 WHERE 构造
# ─────────────────────────────────────────────────────────────

def _build_where(*, start_date: str, end_date: str, tz_basis: str,
                 platform: str | None = None,
                 account_id: str | None = None,
                 campaign_id: str | None = None,
                 adgroup_id: str | None = None,
                 ad_id: str | None = None,
                 content_id: int | None = None,
                 name_filter: str | None = None) -> tuple[str, list]:
    col = _resolve_tz_col(tz_basis)
    clauses = [f"{col} BETWEEN %s AND %s"]
    params: list = [start_date, end_date]
    if platform:
        clauses.append("platform = %s")
        params.append(platform)
    if account_id:
        clauses.append("account_id = %s")
        params.append(account_id)
    if campaign_id:
        clauses.append("campaign_id = %s")
        params.append(campaign_id)
    if adgroup_id:
        clauses.append("adgroup_id = %s")
        params.append(adgroup_id)
    if ad_id:
        clauses.append("ad_id = %s")
        params.append(ad_id)
    if content_id is not None:
        clauses.append("content_id = %s")
        params.append(content_id)
    if name_filter:
        clauses.append("(ad_name LIKE %s OR campaign_name LIKE %s OR adgroup_name LIKE %s)")
        like = f"%{name_filter}%"
        params.extend([like, like, like])
    return " AND ".join(clauses), params


# 衍生 ROI 表达式（统一在 SQL 层动态算，避免 spend 修订后失真）
_ROI_EXPR = {
    "roi_1d":   "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_1d)/SUM(spend),   6) ELSE NULL END",
    "roi_3d":   "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_3d)/SUM(spend),   6) ELSE NULL END",
    "roi_7d":   "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_7d)/SUM(spend),   6) ELSE NULL END",
    "roi_14d":  "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_14d)/SUM(spend),  6) ELSE NULL END",
    "roi_30d":  "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_30d)/SUM(spend),  6) ELSE NULL END",
    "roi_90d":  "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_90d)/SUM(spend),  6) ELSE NULL END",
    "roi_120d": "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(cum_recharge_120d)/SUM(spend), 6) ELSE NULL END",
    "roi_total": "CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(total_recharge_amount)/SUM(spend), 6) ELSE NULL END",
}

_BASE_AGG_SELECT = """
    SUM(spend)                AS total_spend,
    SUM(impressions)          AS total_impressions,
    SUM(clicks)               AS total_clicks,
    SUM(inline_link_clicks)   AS total_inline_link_clicks,
    SUM(landing_page_view)    AS total_landing_page_view,
    SUM(conversion)           AS total_conversion,
    SUM(install)              AS total_install,
    SUM(activation)           AS total_activation,
    SUM(registration)         AS total_registration,
    SUM(purchase)             AS total_purchase,
    SUM(cohort_activations)   AS total_cohort_activations,
    SUM(cohort_first_chargers) AS total_cohort_first_chargers,
    SUM(cohort_pay_users)     AS total_cohort_pay_users,
    SUM(first_sub_count)      AS total_first_sub_count,
    SUM(first_sub_amount)     AS total_first_sub_amount,
    SUM(renew_sub_count)      AS total_renew_sub_count,
    SUM(renew_sub_amount)     AS total_renew_sub_amount,
    SUM(first_iap_count)      AS total_first_iap_count,
    SUM(first_iap_amount)     AS total_first_iap_amount,
    SUM(repeat_iap_count)     AS total_repeat_iap_count,
    SUM(repeat_iap_amount)    AS total_repeat_iap_amount,
    SUM(total_recharge_amount) AS total_recharge_amount,
    SUM(cum_recharge_1d)      AS total_cum_recharge_1d,
    SUM(cum_recharge_3d)      AS total_cum_recharge_3d,
    SUM(cum_recharge_7d)      AS total_cum_recharge_7d,
    SUM(cum_recharge_14d)     AS total_cum_recharge_14d,
    SUM(cum_recharge_30d)     AS total_cum_recharge_30d,
    SUM(cum_recharge_90d)     AS total_cum_recharge_90d,
    SUM(cum_recharge_120d)    AS total_cum_recharge_120d
"""


def _roi_select_clause() -> str:
    return ",\n    ".join(f"{expr} AS {name}" for name, expr in _ROI_EXPR.items())


# ─────────────────────────────────────────────────────────────
#  查询：总览 / 日趋势 / 维度聚合 / 排行 / cohort 单条
# ─────────────────────────────────────────────────────────────

def get_overview(start_date: str, end_date: str, *,
                 tz_basis: str = "account_local",
                 platform: str | None = None,
                 account_id: str | None = None,
                 campaign_id: str | None = None,
                 adgroup_id: str | None = None,
                 ad_id: str | None = None,
                 content_id: int | None = None) -> dict:
    where, params = _build_where(
        start_date=start_date, end_date=end_date, tz_basis=tz_basis,
        platform=platform, account_id=account_id,
        campaign_id=campaign_id, adgroup_id=adgroup_id,
        ad_id=ad_id, content_id=content_id,
    )
    sql = f"""
        SELECT
            {_BASE_AGG_SELECT},
            {_roi_select_clause()}
        FROM biz_attribution_ad_daily
        WHERE {where}
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone() or {}
    return _normalize_row(row)


def get_daily_trend(start_date: str, end_date: str, *,
                    tz_basis: str = "account_local",
                    platform: str | None = None,
                    account_id: str | None = None,
                    campaign_id: str | None = None,
                    adgroup_id: str | None = None,
                    ad_id: str | None = None,
                    content_id: int | None = None) -> list[dict]:
    """按 ds 出日趋势（含 N 日 ROI）"""
    tz_col = _resolve_tz_col(tz_basis)
    where, params = _build_where(
        start_date=start_date, end_date=end_date, tz_basis=tz_basis,
        platform=platform, account_id=account_id,
        campaign_id=campaign_id, adgroup_id=adgroup_id,
        ad_id=ad_id, content_id=content_id,
    )
    sql = f"""
        SELECT
            {tz_col} AS ds,
            {_BASE_AGG_SELECT},
            {_roi_select_clause()}
        FROM biz_attribution_ad_daily
        WHERE {where}
        GROUP BY {tz_col}
        ORDER BY {tz_col} ASC
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_normalize_row(r) for r in rows]


def get_aggregated(start_date: str, end_date: str, *,
                   group_by: str = "ad",
                   tz_basis: str = "account_local",
                   platform: str | None = None,
                   account_id: str | None = None,
                   campaign_id: str | None = None,
                   adgroup_id: str | None = None,
                   ad_id: str | None = None,
                   content_id: int | None = None,
                   name_filter: str | None = None,
                   order_by: str = "total_spend",
                   order_dir: str = "desc",
                   page: int = 1, page_size: int = 50) -> dict:
    """按维度聚合（ad / adgroup / campaign / account），分页返回"""
    if group_by not in _ALLOWED_GROUP_BY:
        group_by = "ad"
    group_cols = _ALLOWED_GROUP_BY[group_by]
    if order_dir.lower() not in ("asc", "desc"):
        order_dir = "desc"

    where, params = _build_where(
        start_date=start_date, end_date=end_date, tz_basis=tz_basis,
        platform=platform, account_id=account_id,
        campaign_id=campaign_id, adgroup_id=adgroup_id,
        ad_id=ad_id, content_id=content_id,
        name_filter=name_filter,
    )
    group_sql = ", ".join(group_cols)

    if order_by in _ROI_EXPR:
        order_expr = _ROI_EXPR[order_by]
    elif order_by.startswith("total_"):
        order_expr = order_by
    else:
        order_expr = "total_spend"

    select_cols = []
    for c in group_cols:
        if c.endswith("_name"):
            select_cols.append(f"MAX({c}) AS {c}")
        else:
            select_cols.append(c)

    base_sql = f"""
        SELECT
            {', '.join(select_cols)},
            {_BASE_AGG_SELECT},
            {_roi_select_clause()}
        FROM biz_attribution_ad_daily
        WHERE {where}
        GROUP BY {group_sql}
    """

    count_sql = f"SELECT COUNT(*) AS cnt FROM ({base_sql}) t"
    page_sql = f"{base_sql} ORDER BY {order_expr} {order_dir} LIMIT %s OFFSET %s"
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    offset = (page - 1) * page_size

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(count_sql, params)
        total = cur.fetchone()["cnt"]
        cur.execute(page_sql, params + [page_size, offset])
        rows = cur.fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "list": [_normalize_row(r) for r in rows],
    }


def get_top_ads(start_date: str, end_date: str, *,
                metric: str = "roi_7d",
                tz_basis: str = "account_local",
                platform: str | None = None,
                account_id: str | None = None,
                limit: int = 20) -> list[dict]:
    """按指定指标取 Top N 广告"""
    if metric not in _ALLOWED_TOP_METRICS:
        metric = "spend"
    limit = min(max(1, int(limit)), 100)
    where, params = _build_where(
        start_date=start_date, end_date=end_date, tz_basis=tz_basis,
        platform=platform, account_id=account_id,
    )
    if metric in _ROI_EXPR:
        order_expr = _ROI_EXPR[metric]
    elif metric == "spend":
        order_expr = "SUM(spend)"
    else:
        order_expr = f"SUM({metric})"

    sql = f"""
        SELECT
            platform, account_id,
            campaign_id, MAX(campaign_name) AS campaign_name,
            adgroup_id, MAX(adgroup_name) AS adgroup_name,
            ad_id, MAX(ad_name) AS ad_name,
            {_BASE_AGG_SELECT},
            {_roi_select_clause()}
        FROM biz_attribution_ad_daily
        WHERE {where}
        GROUP BY platform, account_id, campaign_id, adgroup_id, ad_id
        ORDER BY {order_expr} DESC
        LIMIT %s
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params + [limit])
        rows = cur.fetchall()
    return [_normalize_row(r) for r in rows]


def get_cohort_curve(*, ds: str, tz_basis: str = "account_local",
                     platform: str | None = None,
                     account_id: str | None = None,
                     campaign_id: str | None = None,
                     adgroup_id: str | None = None,
                     ad_id: str | None = None) -> dict:
    """指定 cohort 日 → 返回 D1/D3/D7/D14/D30/D90/D120 ROI 曲线（聚合到一行）"""
    where, params = _build_where(
        start_date=ds, end_date=ds, tz_basis=tz_basis,
        platform=platform, account_id=account_id,
        campaign_id=campaign_id, adgroup_id=adgroup_id, ad_id=ad_id,
    )
    sql = f"""
        SELECT
            {_BASE_AGG_SELECT},
            {_roi_select_clause()}
        FROM biz_attribution_ad_daily
        WHERE {where}
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone() or {}
    out = _normalize_row(row)
    out["ds"] = ds
    out["tz_basis"] = tz_basis
    return out


# ─────────────────────────────────────────────────────────────
#  通用：行规范化（DECIMAL/Date 转可序列化值）
# ─────────────────────────────────────────────────────────────

def _normalize_row(row: dict) -> dict:
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat() if hasattr(v, "year") else str(v)
        else:
            try:
                if isinstance(v, (int, float, str)):
                    out[k] = v
                else:
                    out[k] = float(v)
            except Exception:
                out[k] = str(v)
    return out


# ─────────────────────────────────────────────────────────────
#  辅助：取最近一次同步覆盖的 ds_la 范围（用于前端默认时间区间）
# ─────────────────────────────────────────────────────────────

def get_data_range() -> dict:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MIN(ds_la) AS min_ds_la, MAX(ds_la) AS max_ds_la, COUNT(*) AS row_cnt "
            "FROM biz_attribution_ad_daily"
        )
        row = cur.fetchone() or {}
    return {
        "min_ds_la": str(row.get("min_ds_la")) if row.get("min_ds_la") else None,
        "max_ds_la": str(row.get("max_ds_la")) if row.get("max_ds_la") else None,
        "row_cnt": int(row.get("row_cnt") or 0),
    }
