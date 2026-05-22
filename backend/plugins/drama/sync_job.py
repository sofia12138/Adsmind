"""sync_drama.py — 剧级映射 & 事实表同步任务

流程：
  1. 从 biz_campaign_daily_normalized 扫描原始广告日报数据
  2. 根据 source_type 字段（或活动名称推断）选择对应解析器
  3. 解析结果写入 ad_drama_mapping（upsert）
  4. 使用 ad_drama_mapping JOIN 日报数据聚合生成 fact_drama_daily（upsert）

核心约束：
  - drama_name_raw 只来自活动名称第 10 字段
  - remark_raw 不参与任何聚合或 content_key 生成
  - 所有失败样本保留原始 campaign_name，方便排查
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from db import get_biz_conn
from plugins.drama import repository as drama_repository
from plugins.drama.repository import build_content_key
from plugins.drama.name_parser import (
    parse_mini_program_campaign_name,
    parse_app_campaign_name,
    ParsedMiniProgramCampaign,
    ParsedAppCampaign,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# source_type 判断
# ─────────────────────────────────────────────────────────────

_MINI_PROGRAM_KEYWORDS = {"小程序", "miniprogram", "mini_program", "mp"}
_APP_KEYWORDS = {"app", "application"}


def _detect_source_type(campaign_name: str, hint: str = "") -> str:
    """
    从 hint（预设 source_type）或活动名称中检测来源类型。
    返回 '小程序' 或 'APP'。
    """
    if hint:
        h = hint.strip().lower()
        if any(k in h for k in _MINI_PROGRAM_KEYWORDS):
            return "小程序"
        if any(k in h for k in _APP_KEYWORDS):
            return "APP"

    # 从活动名称第 4 字段推断（小程序解析器字段定义）
    parts = campaign_name.split("-")
    if len(parts) >= 4:
        f4 = parts[3].strip().lower()
        if any(k in f4 for k in _MINI_PROGRAM_KEYWORDS):
            return "小程序"
        if any(k in f4 for k in _APP_KEYWORDS):
            return "APP"

    return "APP"


# ─────────────────────────────────────────────────────────────
# 解析单条活动名称 → mapping 行
# ─────────────────────────────────────────────────────────────

def _parse_campaign_to_mapping_row(
    *,
    platform: str,
    account_id: str,
    campaign_id: str,
    campaign_name: str,
    adset_id: str = "",
    adset_name: str = "",
    ad_id: str = "",
    ad_name: str = "",
    channel: str = "",
    source_type_hint: str = "",
) -> dict:
    """
    根据 source_type 选择解析器，返回可直接写入 ad_drama_mapping 的 dict。
    """
    source_type = _detect_source_type(campaign_name, source_type_hint)

    if source_type == "小程序":
        parsed = parse_mini_program_campaign_name(campaign_name)
        content_key = build_content_key(
            source_type,
            parsed.drama_id,
            parsed.localized_drama_name,
        )
        return {
            "source_type": source_type,
            "platform": platform,
            "channel": channel,
            "account_id": account_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "adset_id": adset_id,
            "adset_name": adset_name,
            "ad_id": ad_id,
            "ad_name": ad_name,
            "drama_id": parsed.drama_id,
            "drama_type": parsed.drama_type,
            "country": parsed.country,
            "drama_name_raw": parsed.drama_name_raw,
            "localized_drama_name": parsed.localized_drama_name,
            "language_code": parsed.language_code,
            "language_tag_raw": parsed.language_tag_raw,
            "buyer_name": parsed.buyer_name,
            "buyer_short_name": "",
            "optimization_type": parsed.optimization_type,
            "bid_type": parsed.bid_type,
            "publish_date": parsed.publish_date,
            "remark_raw": parsed.remark_raw,
            "content_key": content_key,
            "match_source": "parser",
            "is_confirmed": 0,
            "parse_status": parsed.parse_status,
            "parse_error": parsed.parse_error,
        }

    elif source_type == "APP":
        parsed_app = parse_app_campaign_name(campaign_name)
        content_key = build_content_key(
            source_type,
            "",  # APP 当前无独立 drama_id 字段
            parsed_app.localized_drama_name,
        )
        return {
            "source_type": source_type,
            "platform": platform,
            "channel": channel,
            "account_id": account_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "adset_id": adset_id,
            "adset_name": adset_name,
            "ad_id": ad_id,
            "ad_name": ad_name,
            "drama_id": "",
            "drama_type": "",
            "country": "",
            "drama_name_raw": parsed_app.drama_name_raw,
            "localized_drama_name": parsed_app.localized_drama_name,
            "language_code": parsed_app.language_code,
            "language_tag_raw": parsed_app.language_tag_raw,
            "buyer_name": "",
            "buyer_short_name": parsed_app.buyer_short_name or "",
            "optimization_type": "",
            "bid_type": "",
            "publish_date": "",
            "remark_raw": parsed_app.remark_raw,
            "content_key": content_key,
            "match_source": "parser",
            "is_confirmed": 0,
            "parse_status": parsed_app.parse_status,
            "parse_error": parsed_app.parse_error,
        }

    else:
        # 未知来源：parse_status=partial，保留原始名称
        return {
            "source_type": "unknown",
            "platform": platform,
            "channel": channel,
            "account_id": account_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "adset_id": adset_id,
            "adset_name": adset_name,
            "ad_id": ad_id,
            "ad_name": ad_name,
            "drama_id": "",
            "drama_type": "",
            "country": "",
            "drama_name_raw": "",
            "localized_drama_name": "",
            "language_code": "unknown",
            "language_tag_raw": None,
            "buyer_name": "",
            "buyer_short_name": "",
            "optimization_type": "",
            "bid_type": "",
            "publish_date": "",
            "remark_raw": None,
            "content_key": "",
            "match_source": "parser",
            "is_confirmed": 0,
            "parse_status": "partial",
            "parse_error": "无法识别 source_type，已记录原始活动名称",
        }


# ─────────────────────────────────────────────────────────────
# 从 biz_campaign_daily_normalized 读取日报数据
# ─────────────────────────────────────────────────────────────

def _fetch_campaign_daily(start_date: str, end_date: str) -> list[dict]:
    """
    从日报表 + 回传转化表中拉取 campaign/day 粒度数据。

    数据来源：
      - spend / impressions / clicks / installs → biz_campaign_daily_normalized
      - registrations / purchase_value          → ad_returned_conversion_daily

    关键约束：
      ad_returned_conversion_daily 唯一键含 country/platform 列且允许 NULL，
      同一 campaign+day 可能存在多行（NULL vs '' 被视为不同键）。
      直接 LEFT JOIN 会导致 SUM(b.spend) 被乘以匹配行数，造成 spend 虚高。
      解决方案：先将 returned_conversion 按 (stat_date, media_source, account_id, campaign_id)
      预聚合为单行子查询，再与 biz 表做 1:1 LEFT JOIN。
    """
    sql = """
        SELECT
            b.stat_date,
            b.platform,
            b.account_id,
            b.campaign_id,
            ANY_VALUE(b.campaign_name)      AS campaign_name,
            SUM(b.spend)                    AS spend,
            SUM(b.impressions)              AS impressions,
            SUM(b.clicks)                   AS clicks,
            SUM(b.installs)                 AS installs,
            COALESCE(r.registrations, 0)    AS registrations,
            COALESCE(r.purchase_value, 0)   AS purchase_value
        FROM biz_campaign_daily_normalized b
        LEFT JOIN (
            -- 预聚合：将 campaign 层级所有行（含 NULL/空 adset_id/ad_id）
            -- 合并为唯一 (stat_date, media_source, account_id, campaign_id) 行。
            -- 必须在子查询内完成，以避免笛卡尔积放大外层 b.spend。
            SELECT
                stat_date,
                media_source,
                account_id,
                campaign_id,
                SUM(registrations_returned) AS registrations,
                SUM(purchase_value_returned) AS purchase_value
            FROM ad_returned_conversion_daily
            WHERE (adset_id IS NULL OR adset_id = '')
              AND (ad_id    IS NULL OR ad_id    = '')
            GROUP BY stat_date, media_source, account_id, campaign_id
        ) r ON r.stat_date    = b.stat_date
           AND r.media_source = b.platform
           AND r.account_id   = b.account_id
           AND r.campaign_id  = b.campaign_id
        WHERE b.stat_date BETWEEN %s AND %s
          AND b.campaign_id IS NOT NULL
          AND b.campaign_id != ''
        GROUP BY b.stat_date, b.platform, b.account_id, b.campaign_id
        ORDER BY b.stat_date, b.platform, b.account_id, b.campaign_id
    """
    with get_biz_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start_date, end_date))
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# 主同步函数
# ─────────────────────────────────────────────────────────────

def run(start_date: str, end_date: str) -> dict:
    """
    同步剧级映射和事实表数据。

    Args:
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date:   结束日期，格式 YYYY-MM-DD

    Returns:
        运行统计 dict，含 mapping_upserted / fact_upserted / failed_count
    """
    logger.info(f"[sync_drama] 开始同步：{start_date} ~ {end_date}")

    # Step 1：拉取日报数据
    daily_rows = _fetch_campaign_daily(start_date, end_date)
    logger.info(f"[sync_drama] 读取到 {len(daily_rows)} 条日报记录")

    if not daily_rows:
        return {"mapping_upserted": 0, "fact_upserted": 0, "failed_count": 0}

    # Step 2：解析活动名称，构建 mapping 行（按 campaign_id 去重解析）
    seen_campaigns: dict[str, dict] = {}  # campaign_id -> mapping_row
    failed_count = 0

    for row in daily_rows:
        cid = row["campaign_id"]
        if cid in seen_campaigns:
            continue
        mapping_row = _parse_campaign_to_mapping_row(
            platform=row["platform"] or "",
            account_id=str(row["account_id"] or ""),
            campaign_id=str(cid),
            campaign_name=row["campaign_name"] or "",
            channel=row.get("channel", ""),
        )
        seen_campaigns[cid] = mapping_row
        if mapping_row["parse_status"] in ("failed", "partial"):
            failed_count += 1

    # Step 3：批量 upsert ad_drama_mapping
    mapping_rows = list(seen_campaigns.values())
    mapping_upserted = drama_repository.upsert_mappings_bulk(mapping_rows)
    logger.info(f"[sync_drama] ad_drama_mapping upserted: {mapping_upserted}")

    # Step 4：构建 fact_drama_daily 行
    # 按 (stat_date, content_key, language_code, platform, account_id, country) 聚合
    fact_key_map: dict[tuple, dict] = {}

    for row in daily_rows:
        cid = row["campaign_id"]
        mapping = seen_campaigns.get(cid)
        if not mapping or not mapping["content_key"]:
            continue

        key = (
            str(row["stat_date"]),
            mapping["source_type"],
            mapping["platform"],
            mapping.get("channel", ""),
            str(row["account_id"] or ""),
            mapping.get("country", ""),
            mapping["content_key"],
            mapping["language_code"],
        )

        if key not in fact_key_map:
            fact_key_map[key] = {
                "stat_date": str(row["stat_date"]),
                "source_type": mapping["source_type"],
                "platform": mapping["platform"],
                "channel": mapping.get("channel", ""),
                "account_id": str(row["account_id"] or ""),
                "country": mapping.get("country", ""),
                "drama_id": mapping["drama_id"],
                "drama_type": mapping["drama_type"],
                "localized_drama_name": mapping["localized_drama_name"],
                "language_code": mapping["language_code"],
                "content_key": mapping["content_key"],
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "installs": 0,
                "registrations": 0,
                "purchase_value": 0.0,
            }

        acc = fact_key_map[key]
        acc["spend"] += float(row.get("spend") or 0)
        acc["impressions"] += int(row.get("impressions") or 0)
        acc["clicks"] += int(row.get("clicks") or 0)
        acc["installs"] += int(row.get("installs") or 0)
        acc["registrations"] += int(row.get("registrations") or 0)
        acc["purchase_value"] += float(row.get("purchase_value") or 0)

    fact_rows = list(fact_key_map.values())
    fact_upserted = drama_repository.upsert_fact_daily_bulk(fact_rows)
    logger.info(f"[sync_drama] fact_drama_daily upserted: {fact_upserted}")
    logger.info(f"[sync_drama] 解析失败/partial: {failed_count} 条活动")

    return {
        "mapping_upserted": mapping_upserted,
        "fact_upserted": fact_upserted,
        "failed_count": failed_count,
    }


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="同步剧级映射和事实表数据")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    result = run(args.start, args.end)
    print(result)
