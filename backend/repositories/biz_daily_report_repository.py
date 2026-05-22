"""Campaign 归一化日报数据访问层 — biz_campaign_daily_normalized (adpilot_biz)"""
from __future__ import annotations

import json
from typing import Optional

from db import get_biz_conn


def _safe_div(a, b) -> Optional[float]:
    """安全除法，分母为零返回 None"""
    if not b:
        return None
    return round(float(a) / float(b), 6)


def _calc_derived(row: dict) -> dict:
    """根据核心指标计算衍生指标"""
    spend = float(row.get("spend", 0) or 0)
    impressions = int(row.get("impressions", 0) or 0)
    clicks = int(row.get("clicks", 0) or 0)
    installs = int(row.get("installs", 0) or 0)
    conversions = int(row.get("conversions", 0) or 0)
    revenue = float(row.get("revenue", 0) or 0)
    return {
        "ctr": _safe_div(clicks, impressions),
        "cpc": _safe_div(spend, clicks),
        "cpm": round(spend / impressions * 1000, 4) if impressions else None,
        "cpi": _safe_div(spend, installs),
        "cpa": _safe_div(spend, conversions),
        "roas": _safe_div(revenue, spend),
    }


def upsert(*, platform: str, account_id: str, campaign_id: str,
           campaign_name: str, stat_date: str,
           spend: float = 0, impressions: int = 0, clicks: int = 0,
           installs: int = 0, conversions: int = 0, revenue: float = 0,
           raw_json: dict | None = None) -> int:
    derived = _calc_derived({
        "spend": spend, "impressions": impressions, "clicks": clicks,
        "installs": installs, "conversions": conversions, "revenue": revenue,
    })
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO biz_campaign_daily_normalized
               (platform, account_id, campaign_id, campaign_name, stat_date,
                spend, impressions, clicks, installs, conversions, revenue,
                ctr, cpc, cpm, cpi, cpa, roas, raw_json)
               VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s)
               ON DUPLICATE KEY UPDATE
                 account_id    = VALUES(account_id),
                 campaign_name = VALUES(campaign_name),
                 spend         = VALUES(spend),
                 impressions   = VALUES(impressions),
                 clicks        = VALUES(clicks),
                 installs      = VALUES(installs),
                 conversions   = VALUES(conversions),
                 revenue       = VALUES(revenue),
                 ctr           = VALUES(ctr),
                 cpc           = VALUES(cpc),
                 cpm           = VALUES(cpm),
                 cpi           = VALUES(cpi),
                 cpa           = VALUES(cpa),
                 roas          = VALUES(roas),
                 raw_json      = VALUES(raw_json)""",
            (platform, account_id, campaign_id, campaign_name, stat_date,
             spend, impressions, clicks, installs, conversions, revenue,
             derived["ctr"], derived["cpc"], derived["cpm"],
             derived["cpi"], derived["cpa"], derived["roas"],
             json.dumps(raw_json, ensure_ascii=False) if raw_json else None),
        )
        conn.commit()
        return cur.lastrowid


def upsert_batch(rows: list[dict]) -> int:
    """批量 upsert 日报数据。rows 中每个 dict 需含 upsert() 的必填字段。"""
    if not rows:
        return 0
    with get_biz_conn() as conn:
        cur = conn.cursor()
        sql = """INSERT INTO biz_campaign_daily_normalized
                 (platform, account_id, campaign_id, campaign_name, stat_date,
                  spend, impressions, clicks, installs, conversions, revenue,
                  ctr, cpc, cpm, cpi, cpa, roas, raw_json)
                 VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s)
                 ON DUPLICATE KEY UPDATE
                   account_id    = VALUES(account_id),
                   campaign_name = VALUES(campaign_name),
                   spend         = VALUES(spend),
                   impressions   = VALUES(impressions),
                   clicks        = VALUES(clicks),
                   installs      = VALUES(installs),
                   conversions   = VALUES(conversions),
                   revenue       = VALUES(revenue),
                   ctr           = VALUES(ctr),
                   cpc           = VALUES(cpc),
                   cpm           = VALUES(cpm),
                   cpi           = VALUES(cpi),
                   cpa           = VALUES(cpa),
                   roas          = VALUES(roas),
                   raw_json      = VALUES(raw_json)"""
        params = []
        for r in rows:
            d = _calc_derived(r)
            params.append((
                r["platform"], r["account_id"], r["campaign_id"],
                r.get("campaign_name", ""), r["stat_date"],
                r.get("spend", 0), r.get("impressions", 0), r.get("clicks", 0),
                r.get("installs", 0), r.get("conversions", 0), r.get("revenue", 0),
                d["ctr"], d["cpc"], d["cpm"], d["cpi"], d["cpa"], d["roas"],
                json.dumps(r["raw_json"], ensure_ascii=False) if r.get("raw_json") else None,
            ))
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


def query(*, platform: str | None = None, account_id: str | None = None,
          campaign_id: str | None = None,
          start_date: str | None = None, end_date: str | None = None,
          limit: int = 500) -> list[dict]:
    clauses = []
    params: list = []
    if platform:
        clauses.append("platform = %s")
        params.append(platform)
    if account_id:
        clauses.append("account_id = %s")
        params.append(account_id)
    if campaign_id:
        clauses.append("campaign_id = %s")
        params.append(campaign_id)
    if start_date:
        clauses.append("stat_date >= %s")
        params.append(start_date)
    if end_date:
        clauses.append("stat_date <= %s")
        params.append(end_date)

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"SELECT * FROM biz_campaign_daily_normalized WHERE {where} ORDER BY stat_date DESC LIMIT %s"
    params.append(limit)

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


# ═══════════════════════════════════════════════════════════
#  聚合查询
# ═══════════════════════════════════════════════════════════

def _build_where(platform: str | None, account_id: str | None,
                 start_date: str, end_date: str,
                 campaign_name: str | None = None) -> tuple[str, list]:
    clauses = ["stat_date BETWEEN %s AND %s"]
    params: list = [start_date, end_date]
    if platform:
        clauses.append("platform = %s")
        params.append(platform)
    if account_id:
        clauses.append("account_id = %s")
        params.append(account_id)
    if campaign_name:
        clauses.append("campaign_name LIKE %s")
        params.append(f"%{campaign_name}%")
    return " AND ".join(clauses), params


def sum_spend_by_stat_date(start_date: str, end_date: str) -> dict[str, float]:
    """按 stat_date 聚合 SUM(spend)，返回 {YYYY-MM-DD: spend_usd}（全平台合计）。

    数据来源是 biz_campaign_daily_normalized，与 Meta / TikTok 平台后台报表 1:1 同源。
    用途：运营面板 ad_spend 的主源 — 跟 AdsMind Meta 操作台对齐口径。
    stat_date 沿用平台报表的日期（一般是账户时区），不再做 LA 日折算。
    """
    out: dict[str, float] = {}
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT stat_date, SUM(spend) AS spend "
            "FROM biz_campaign_daily_normalized "
            "WHERE stat_date BETWEEN %s AND %s "
            "GROUP BY stat_date",
            (start_date, end_date),
        )
        for row in cur.fetchall():
            ds = row.get("stat_date")
            ds_str = ds.strftime("%Y-%m-%d") if hasattr(ds, "strftime") else str(ds)[:10]
            try:
                out[ds_str] = round(float(row.get("spend") or 0), 4)
            except (TypeError, ValueError):
                out[ds_str] = 0.0
    return out


def get_overview(start_date: str, end_date: str,
                 platform: str | None = None,
                 account_id: str | None = None) -> dict:
    where, params = _build_where(platform, account_id, start_date, end_date)
    sql = f"""
        SELECT
            COALESCE(SUM(spend), 0)        AS total_spend,
            COALESCE(SUM(impressions), 0)  AS total_impressions,
            COALESCE(SUM(clicks), 0)       AS total_clicks,
            COALESCE(SUM(installs), 0)     AS total_installs,
            COALESCE(SUM(conversions), 0)  AS total_conversions,
            COALESCE(SUM(revenue), 0)      AS total_revenue
        FROM biz_campaign_daily_normalized
        WHERE {where}
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()

    s  = float(row["total_spend"])
    im = int(row["total_impressions"])
    cl = int(row["total_clicks"])
    ins = int(row["total_installs"])
    cv = int(row["total_conversions"])
    rv = float(row["total_revenue"])

    row["total_spend"]   = s
    row["total_revenue"] = rv
    row["avg_ctr"]  = _safe_div(cl, im)
    row["avg_cpc"]  = _safe_div(s, cl)
    row["avg_cpm"]  = round(s / im * 1000, 4) if im else None
    row["avg_cpi"]  = _safe_div(s, ins)
    row["avg_cpa"]  = _safe_div(s, cv)
    row["avg_roas"] = _safe_div(rv, s)
    return row


_ALLOWED_ORDER_COLS = {
    "stat_date", "platform", "campaign_name", "spend", "impressions",
    "clicks", "installs", "conversions", "revenue", "ctr", "cpc",
    "cpm", "cpi", "cpa", "roas",
}


def get_campaign_daily_list(start_date: str, end_date: str, *,
                            platform: str | None = None,
                            account_id: str | None = None,
                            campaign_name: str | None = None,
                            page: int = 1, page_size: int = 20,
                            order_by: str = "stat_date",
                            order_dir: str = "desc") -> dict:
    where, params = _build_where(platform, account_id, start_date, end_date, campaign_name)

    if order_by not in _ALLOWED_ORDER_COLS:
        order_by = "stat_date"
    if order_dir.lower() not in ("asc", "desc"):
        order_dir = "desc"

    with get_biz_conn() as conn:
        cur = conn.cursor()

        cur.execute(f"SELECT COUNT(*) AS cnt FROM biz_campaign_daily_normalized WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * page_size
        sql = f"""
            SELECT platform, account_id, campaign_id, campaign_name,
                   stat_date, spend, impressions, clicks, installs,
                   conversions, revenue, ctr, cpc, cpm, cpi, cpa, roas
            FROM biz_campaign_daily_normalized
            WHERE {where}
            ORDER BY {order_by} {order_dir}
            LIMIT %s OFFSET %s
        """
        cur.execute(sql, params + [page_size, offset])
        rows = cur.fetchall()

    for r in rows:
        if r.get("stat_date"):
            r["stat_date"] = str(r["stat_date"])

    return {"total": total, "list": rows, "page": page, "page_size": page_size}


def get_campaign_aggregated(start_date: str, end_date: str, *,
                            platform: str | None = None,
                            account_id: str | None = None,
                            campaign_name: str | None = None,
                            order_by: str = "total_spend",
                            order_dir: str = "desc") -> list[dict]:
    where, params = _build_where(platform, account_id, start_date, end_date, campaign_name)
    order_col = order_by if order_by in _AGG_ORDER else "total_spend"
    if order_dir.lower() not in ("asc", "desc"):
        order_dir = "desc"
    sql = f"""
        SELECT platform, account_id, campaign_id,
               MAX(campaign_name)             AS campaign_name,
               SUM(spend)                     AS total_spend,
               SUM(revenue)                   AS total_revenue,
               SUM(impressions)               AS total_impressions,
               SUM(clicks)                    AS total_clicks,
               SUM(installs)                  AS total_installs,
               SUM(conversions)               AS total_conversions,
               CASE WHEN SUM(impressions)>0 THEN ROUND(SUM(clicks)/SUM(impressions),6) ELSE NULL END AS ctr,
               CASE WHEN SUM(clicks)>0      THEN ROUND(SUM(spend)/SUM(clicks),4)      ELSE NULL END AS cpc,
               CASE WHEN SUM(impressions)>0 THEN ROUND(SUM(spend)/SUM(impressions)*1000,4) ELSE NULL END AS cpm,
               CASE WHEN SUM(installs)>0    THEN ROUND(SUM(spend)/SUM(installs),4)    ELSE NULL END AS cpi,
               CASE WHEN SUM(conversions)>0 THEN ROUND(SUM(spend)/SUM(conversions),4) ELSE NULL END AS cpa,
               CASE WHEN SUM(spend)>0       THEN ROUND(SUM(revenue)/SUM(spend),4)     ELSE NULL END AS roas
        FROM biz_campaign_daily_normalized
        WHERE {where}
        GROUP BY platform, account_id, campaign_id
        ORDER BY {order_col} {order_dir}
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


_AGG_ORDER = {
    "total_spend", "total_revenue", "total_impressions", "total_clicks",
    "total_installs", "total_conversions", "ctr", "cpc", "cpm", "cpi", "cpa", "roas",
    "campaign_name",
}

_ALLOWED_METRICS = {"spend", "revenue", "clicks", "installs", "conversions", "roas"}


def get_top_campaigns(start_date: str, end_date: str, *,
                      platform: str | None = None,
                      account_id: str | None = None,
                      metric: str = "spend",
                      limit: int = 20) -> list[dict]:
    where, params = _build_where(platform, account_id, start_date, end_date)

    if metric not in _ALLOWED_METRICS:
        metric = "spend"
    limit = min(max(limit, 1), 100)

    if metric == "roas":
        order_expr = "CASE WHEN SUM(spend) > 0 THEN SUM(revenue)/SUM(spend) ELSE 0 END"
    else:
        order_expr = f"SUM({metric})"

    sql = f"""
        SELECT
            platform,
            account_id,
            campaign_id,
            MAX(campaign_name)             AS campaign_name,
            SUM(spend)                     AS total_spend,
            SUM(impressions)               AS total_impressions,
            SUM(clicks)                    AS total_clicks,
            SUM(installs)                  AS total_installs,
            SUM(conversions)               AS total_conversions,
            SUM(revenue)                   AS total_revenue,
            CASE WHEN SUM(spend) > 0
                 THEN ROUND(SUM(revenue)/SUM(spend), 4)
                 ELSE NULL END             AS avg_roas
        FROM biz_campaign_daily_normalized
        WHERE {where}
        GROUP BY platform, account_id, campaign_id
        ORDER BY {order_expr} DESC
        LIMIT %s
    """
    params.append(limit)

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
