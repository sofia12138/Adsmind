"""优化师人效数据访问层 — campaign_optimizer_mapping + fact_optimizer_daily + optimizer_default_rules"""
from __future__ import annotations

from typing import Optional

from db import get_biz_conn


# ---------------------------------------------------------------------------
# campaign_optimizer_mapping — 写入（支持 match_source / match_confidence）
# ---------------------------------------------------------------------------

def upsert_mapping_bulk(rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO campaign_optimizer_mapping
          (source_type, platform, channel, account_id, campaign_id, campaign_name,
           optimizer_name_raw, optimizer_name_normalized, optimizer_source,
           parse_status, parse_error,
           optimizer_match_source, optimizer_match_confidence, optimizer_match_position)
        VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s,%s)
        ON DUPLICATE KEY UPDATE
          campaign_name              = VALUES(campaign_name),
          optimizer_name_raw         = VALUES(optimizer_name_raw),
          optimizer_name_normalized  = VALUES(optimizer_name_normalized),
          optimizer_source           = VALUES(optimizer_source),
          parse_status               = VALUES(parse_status),
          parse_error                = VALUES(parse_error),
          optimizer_match_source     = VALUES(optimizer_match_source),
          optimizer_match_confidence = VALUES(optimizer_match_confidence),
          optimizer_match_position   = VALUES(optimizer_match_position)
    """
    params = []
    for r in rows:
        params.append((
            r["source_type"], r["platform"], r.get("channel", ""),
            r["account_id"], r["campaign_id"], r["campaign_name"],
            r["optimizer_name_raw"], r["optimizer_name_normalized"],
            r.get("optimizer_source", "campaign_name"),
            r["parse_status"], r.get("parse_error"),
            r.get("optimizer_match_source", "campaign_name"),
            r.get("optimizer_match_confidence", 0.90),
            r.get("optimizer_match_position", ""),
        ))
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# campaign_optimizer_mapping — 读取已有映射
# ---------------------------------------------------------------------------

def get_existing_mappings(campaign_ids: list[str]) -> dict[str, dict]:
    """按 campaign_id 批量获取已有映射记录"""
    if not campaign_ids:
        return {}
    placeholders = ",".join(["%s"] * len(campaign_ids))
    sql = f"""
        SELECT campaign_id, optimizer_name_raw, optimizer_name_normalized,
               optimizer_match_source, optimizer_match_confidence
        FROM campaign_optimizer_mapping
        WHERE campaign_id IN ({placeholders})
          AND optimizer_name_normalized != '未识别'
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, campaign_ids)
        rows = cur.fetchall()
    return {r["campaign_id"]: r for r in rows}


# ---------------------------------------------------------------------------
# optimizer_default_rules — CRUD
# ---------------------------------------------------------------------------

def get_all_default_rules() -> list[dict]:
    """获取所有启用的默认规则，按 priority DESC 排序"""
    sql = """
        SELECT id, source_type, platform, channel, account_id, country,
               optimizer_name, priority, is_enabled
        FROM optimizer_default_rules
        WHERE is_enabled = 1
        ORDER BY priority DESC
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()


def get_default_rules_all_for_api() -> list[dict]:
    """获取所有默认规则（含禁用的），供前端管理"""
    sql = """
        SELECT id, source_type, platform, channel, account_id, country,
               optimizer_name, priority, is_enabled, created_at, updated_at
        FROM optimizer_default_rules
        ORDER BY priority DESC, id DESC
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()


def upsert_default_rule(rule: dict) -> int:
    sql = """
        INSERT INTO optimizer_default_rules
          (source_type, platform, channel, account_id, country,
           optimizer_name, priority, is_enabled)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          optimizer_name = VALUES(optimizer_name),
          priority       = VALUES(priority),
          is_enabled     = VALUES(is_enabled)
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (
            rule.get("source_type", ""),
            rule.get("platform", ""),
            rule.get("channel", ""),
            rule.get("account_id", ""),
            rule.get("country", ""),
            rule["optimizer_name"],
            rule.get("priority", 0),
            rule.get("is_enabled", 1),
        ))
        conn.commit()
        return cur.rowcount


def delete_default_rule(rule_id: int) -> int:
    sql = "DELETE FROM optimizer_default_rules WHERE id = %s"
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (rule_id,))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# fact_optimizer_daily — 写入
# ---------------------------------------------------------------------------

def upsert_fact_daily_bulk(rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO fact_optimizer_daily
          (stat_date, source_type, platform, channel, account_id, country,
           optimizer_name, spend, impressions, clicks, installs,
           registrations, purchase_value, campaign_count)
        VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s)
        ON DUPLICATE KEY UPDATE
          spend          = VALUES(spend),
          impressions    = VALUES(impressions),
          clicks         = VALUES(clicks),
          installs       = VALUES(installs),
          registrations  = VALUES(registrations),
          purchase_value = VALUES(purchase_value),
          campaign_count = VALUES(campaign_count)
    """
    params = []
    for r in rows:
        params.append((
            r["stat_date"], r["source_type"], r["platform"],
            r.get("channel", ""), r["account_id"], r.get("country", ""),
            r["optimizer_name"],
            r.get("spend", 0), r.get("impressions", 0),
            r.get("clicks", 0), r.get("installs", 0),
            r.get("registrations", 0), r.get("purchase_value", 0),
            r.get("campaign_count", 0),
        ))
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# 汇总查询
# ---------------------------------------------------------------------------

def query_optimizer_summary(
    start_date: str,
    end_date: str,
    *,
    platform: Optional[str] = None,
    source_type: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict]:
    """按优化师维度聚合，返回汇总数据（默认按 total_spend DESC）"""
    clauses = ["stat_date BETWEEN %s AND %s"]
    params: list = [start_date, end_date]

    if platform:
        clauses.append("platform = %s")
        params.append(platform)
    if source_type:
        clauses.append("source_type = %s")
        params.append(source_type)

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            optimizer_name,
            SUM(spend)                            AS total_spend,
            SUM(impressions)                      AS impressions,
            SUM(clicks)                           AS clicks,
            SUM(installs)                         AS installs,
            SUM(registrations)                    AS registrations,
            SUM(purchase_value)                   AS purchase_value,
            SUM(campaign_count)                   AS campaign_count,
            COUNT(DISTINCT stat_date)             AS active_days,
            CASE WHEN SUM(spend) > 0
                 THEN ROUND(SUM(purchase_value) / SUM(spend), 4) ELSE NULL END AS roas
        FROM fact_optimizer_daily
        WHERE {where}
        GROUP BY optimizer_name
        ORDER BY total_spend DESC
    """

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    if keyword:
        kw = keyword.strip().upper()
        rows = [r for r in rows if kw in (r.get("optimizer_name") or "").upper()]

    return rows


def query_match_source_distribution(
    start_date: str,
    end_date: str,
    *,
    platform: Optional[str] = None,
) -> list[dict]:
    """查询匹配来源分布统计"""
    clauses = ["b.stat_date BETWEEN %s AND %s"]
    params: list = [start_date, end_date]

    if platform:
        clauses.append("b.platform = %s")
        params.append(platform)

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            COALESCE(m.optimizer_match_source, 'campaign_name') AS match_source,
            COUNT(DISTINCT m.campaign_id) AS campaign_count,
            SUM(b.spend) AS total_spend
        FROM biz_campaign_daily_normalized b
        JOIN campaign_optimizer_mapping m
          ON m.platform    = b.platform
         AND m.account_id  = b.account_id
         AND m.campaign_id = b.campaign_id
        WHERE {where}
        GROUP BY match_source
        ORDER BY total_spend DESC
    """

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def query_optimizer_detail(
    start_date: str,
    end_date: str,
    optimizer_name: str,
    *,
    platform: Optional[str] = None,
) -> list[dict]:
    """查看单个优化师下的 campaign 明细"""
    clauses = [
        "b.stat_date BETWEEN %s AND %s",
        "m.optimizer_name_normalized = %s",
    ]
    params: list = [start_date, end_date, optimizer_name]

    if platform:
        clauses.append("b.platform = %s")
        params.append(platform)

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            b.campaign_id,
            ANY_VALUE(b.campaign_name)  AS campaign_name,
            b.platform,
            b.account_id,
            ANY_VALUE(m.optimizer_match_source) AS match_source,
            ANY_VALUE(m.optimizer_match_confidence) AS match_confidence,
            ANY_VALUE(m.optimizer_match_position) AS match_position,
            SUM(b.spend)               AS spend,
            SUM(b.impressions)         AS impressions,
            SUM(b.clicks)              AS clicks,
            SUM(b.installs)            AS installs,
            SUM(b.revenue)             AS purchase_value,
            COUNT(DISTINCT b.stat_date) AS active_days,
            CASE WHEN SUM(b.spend) > 0
                 THEN ROUND(SUM(b.revenue) / SUM(b.spend), 4)
                 ELSE NULL END         AS roas
        FROM biz_campaign_daily_normalized b
        JOIN campaign_optimizer_mapping m
          ON m.platform     = b.platform
         AND m.account_id   = b.account_id
         AND m.campaign_id  = b.campaign_id
        WHERE {where}
        GROUP BY b.campaign_id, b.platform, b.account_id
        ORDER BY spend DESC
    """

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


# ═══════════════════════════════════════════════════════════
#  Attribution 版本：从 biz_attribution_ad_daily 取真实充值
#
#  注意命名差异：
#  - mapping.platform = meta / tiktok      ↔  attribution.platform = facebook / tiktok
#  - mapping.account_id 带 act_ 前缀(Meta) ↔  attribution.account_id 无前缀
#  → JOIN ON 子句里做 CASE 转换
# ═══════════════════════════════════════════════════════════

def query_optimizer_summary_blend(
    start_date: str,
    end_date: str,
    *,
    platform: Optional[str] = None,
    source_type: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict]:
    """按优化师维度聚合（blend 数据源）

    spend / impressions / clicks / installs → biz_campaign_daily_normalized 全量
    registrations / purchase_value          → biz_attribution_ad_daily + intraday 兜底

    JOIN 路径：
      biz_campaign_daily_normalized n
        JOIN campaign_optimizer_mapping m
          ON (n.platform, n.account_id, n.campaign_id) = (m.platform, m.account_id, m.campaign_id)
        LEFT JOIN attr_subquery a   -- daily 优先 + intraday 兜底
          ON (n.stat_date, n.platform, n.account_id, n.campaign_id) = (a.d, a.plat, a.acc, a.key_id)
    """
    # 复用 biz_blend_service 的 attribution 双源 helper（campaign 粒度）
    from services.biz_blend_service import _attr_subquery

    n_clauses = ["n.stat_date BETWEEN %s AND %s"]
    n_params: list = [start_date, end_date]
    if platform:
        n_clauses.append("n.platform = %s")
        n_params.append(platform.lower())
    if source_type:
        n_clauses.append("m.source_type = %s")
        n_params.append(source_type)
    n_where = " AND ".join(n_clauses)

    attr_sql, attr_args = _attr_subquery("campaign", start_date, end_date, platform, None)

    sql = f"""
        SELECT
            m.optimizer_name_normalized            AS optimizer_name,
            SUM(n.spend)                           AS total_spend,
            SUM(n.impressions)                     AS impressions,
            SUM(n.clicks)                          AS clicks,
            SUM(n.installs)                        AS installs,
            COALESCE(SUM(a.attr_registrations), 0) AS registrations,
            COALESCE(SUM(a.attr_revenue), 0)       AS purchase_value,
            COUNT(DISTINCT n.campaign_id)          AS campaign_count,
            COUNT(DISTINCT n.stat_date)            AS active_days,
            CASE WHEN SUM(n.spend) > 0
                 THEN ROUND(COALESCE(SUM(a.attr_revenue), 0) / SUM(n.spend), 4)
                 ELSE NULL END                                            AS roas
        FROM biz_campaign_daily_normalized n
        JOIN campaign_optimizer_mapping m
          ON m.platform    = n.platform
         AND m.account_id  = n.account_id
         AND m.campaign_id = n.campaign_id
        LEFT JOIN ({attr_sql}) a
            ON a.d      = n.stat_date
           AND a.plat   = n.platform
           AND a.acc    = n.account_id
           AND a.key_id = n.campaign_id
        WHERE {n_where}
        GROUP BY m.optimizer_name_normalized
        ORDER BY total_spend DESC
    """
    args = attr_args + n_params

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall()

    if keyword:
        kw = keyword.strip().upper()
        rows = [r for r in rows if kw in (r.get("optimizer_name") or "").upper()]

    return rows


def query_optimizer_summary_attribution(
    start_date: str,
    end_date: str,
    *,
    platform: Optional[str] = None,
    source_type: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict]:
    """按优化师维度聚合（attribution 数据源 + JOIN mapping）。

    与 query_optimizer_summary 接口一致，但底层数据源换成 biz_attribution_ad_daily：
      - spend / impressions / clicks / installs → attribution（数仓真值，与 normalized 量级一致）
      - registrations / purchase_value          → attribution.registration / total_recharge_amount
    avg_daily_spend / active_days / campaign_count 都按 attribution 行重算。

    JOIN 注意点：
      - mapping.platform = meta / tiktok      ↔  attribution.platform = facebook / tiktok
      - mapping.account_id 带 act_ 前缀 (Meta) ↔  attribution.account_id 无前缀
      - source_type 来自 mapping，attribution 表没有该列
    """
    clauses = ["a.ds_account_local BETWEEN %s AND %s"]
    params: list = [start_date, end_date]

    if platform:
        norm_p = "facebook" if platform.lower() == "meta" else platform.lower()
        clauses.append("a.platform = %s")
        params.append(norm_p)
    if source_type:
        clauses.append("m.source_type = %s")
        params.append(source_type)

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            m.optimizer_name_normalized            AS optimizer_name,
            SUM(a.spend)                           AS total_spend,
            SUM(a.impressions)                     AS impressions,
            SUM(a.clicks)                          AS clicks,
            SUM(a.activation)                      AS installs,
            SUM(a.registration)                    AS registrations,
            SUM(a.total_recharge_amount)           AS purchase_value,
            COUNT(DISTINCT a.campaign_id)          AS campaign_count,
            COUNT(DISTINCT a.ds_account_local)     AS active_days,
            CASE WHEN SUM(a.spend) > 0
                 THEN ROUND(SUM(a.total_recharge_amount) / SUM(a.spend), 4)
                 ELSE NULL END                                            AS roas
        FROM biz_attribution_ad_daily a
        JOIN campaign_optimizer_mapping m
          ON m.campaign_id = a.campaign_id
         AND CASE WHEN m.platform = 'meta' THEN 'facebook' ELSE m.platform END = a.platform
         AND CASE WHEN m.account_id LIKE 'act\\_%%' THEN SUBSTRING(m.account_id, 5) ELSE m.account_id END = a.account_id
        WHERE {where}
        GROUP BY m.optimizer_name_normalized
        ORDER BY total_spend DESC
    """

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    if keyword:
        kw = keyword.strip().upper()
        rows = [r for r in rows if kw in (r.get("optimizer_name") or "").upper()]

    return rows


def query_optimizer_detail_attribution(
    start_date: str,
    end_date: str,
    optimizer_name: str,
    *,
    platform: Optional[str] = None,
) -> list[dict]:
    """单个优化师下 campaign 明细（attribution 数据源 + JOIN mapping）"""
    clauses = [
        "a.ds_account_local BETWEEN %s AND %s",
        "m.optimizer_name_normalized = %s",
    ]
    params: list = [start_date, end_date, optimizer_name]

    if platform:
        norm_p = "facebook" if platform.lower() == "meta" else platform.lower()
        clauses.append("a.platform = %s")
        params.append(norm_p)

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            a.campaign_id,
            ANY_VALUE(a.campaign_name)  AS campaign_name,
            CASE WHEN a.platform = 'facebook' THEN 'meta' ELSE a.platform END  AS platform,
            a.account_id,
            ANY_VALUE(m.optimizer_match_source)     AS match_source,
            ANY_VALUE(m.optimizer_match_confidence) AS match_confidence,
            ANY_VALUE(m.optimizer_match_position)   AS match_position,
            SUM(a.spend)                            AS spend,
            SUM(a.impressions)                      AS impressions,
            SUM(a.clicks)                           AS clicks,
            SUM(a.activation)                       AS installs,
            SUM(a.registration)                     AS registrations,
            SUM(a.total_recharge_amount)            AS purchase_value,
            COUNT(DISTINCT a.ds_account_local)      AS active_days,
            CASE WHEN SUM(a.spend) > 0
                 THEN ROUND(SUM(a.total_recharge_amount) / SUM(a.spend), 4)
                 ELSE NULL END                      AS roas
        FROM biz_attribution_ad_daily a
        JOIN campaign_optimizer_mapping m
          ON m.campaign_id = a.campaign_id
         AND CASE WHEN m.platform = 'meta' THEN 'facebook' ELSE m.platform END = a.platform
         AND CASE WHEN m.account_id LIKE 'act_%%' THEN SUBSTRING(m.account_id, 5) ELSE m.account_id END = a.account_id
        WHERE {where}
        GROUP BY a.campaign_id, a.platform, a.account_id
        ORDER BY spend DESC
    """

    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
