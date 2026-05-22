"""sync_optimizer.py — 优化师映射 & 事实表同步任务（名单校验版）

匹配流程：
  1. 加载 optimizer_directory 名单构建匹配器
  2. 从 biz_campaign_daily_normalized 扫描 campaign 日报
  3. 按 source_type 解析 campaign_name 候选字段
  4. 候选值必须在 optimizer_directory 中匹配到 name/code/aliases
  5. 匹配不到的归为"未识别"，消耗不丢失
  6. 写入 campaign_optimizer_mapping + fact_optimizer_daily
"""
from __future__ import annotations

import logging

from db import get_biz_conn
from plugins.optimizer import repository_performance as optimizer_performance_repository
from plugins.optimizer import repository_directory as optimizer_directory_repository
from plugins.optimizer.name_parser import (
    detect_source_type,
    resolve_optimizer,
    OptimizerDirectoryMatcher,
    UNKNOWN_OPTIMIZER,
    MATCH_SOURCE_UNASSIGNED,
)

logger = logging.getLogger(__name__)


def _fetch_campaign_daily(start_date: str, end_date: str) -> list[dict]:
    """从 biz_campaign_daily_normalized + 回传表拉取 campaign/day 数据"""
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
            SELECT
                stat_date, media_source, account_id, campaign_id,
                SUM(registrations_returned)  AS registrations,
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


def _clean_fact_daily(start_date: str, end_date: str):
    """清理该日期范围内的旧 fact 数据，确保重建时不残留脏数据"""
    sql = "DELETE FROM fact_optimizer_daily WHERE stat_date BETWEEN %s AND %s"
    with get_biz_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start_date, end_date))
            deleted = cur.rowcount
            conn.commit()
    if deleted:
        logger.info(f"[sync_optimizer] 清理旧 fact_optimizer_daily {deleted} 行 ({start_date}~{end_date})")


def run(start_date: str, end_date: str) -> dict:
    logger.info(f"[sync_optimizer] 开始同步：{start_date} ~ {end_date}")

    # 加载优化师名单构建匹配器
    directory_rows = optimizer_directory_repository.get_active_directory()
    matcher = OptimizerDirectoryMatcher(directory_rows)
    logger.info(f"[sync_optimizer] 优化师名单加载完成，共 {len(directory_rows)} 条记录")

    if matcher.is_empty:
        logger.warning("[sync_optimizer] 优化师名单为空，所有 campaign 将归为未识别")

    daily_rows = _fetch_campaign_daily(start_date, end_date)
    logger.info(f"[sync_optimizer] 读取到 {len(daily_rows)} 条日报记录")

    if not daily_rows:
        return {"mapping_upserted": 0, "fact_upserted": 0, "failed_count": 0,
                "match_stats": {}}

    # Step 1: 按 campaign_id 去重，基于名单校验解析优化师
    seen: dict[str, dict] = {}
    failed_count = 0
    match_stats: dict[str, int] = {}
    position_stats: dict[str, int] = {}

    for row in daily_rows:
        cid = row["campaign_id"]
        if cid in seen:
            continue

        cname = row["campaign_name"] or ""
        source_type = detect_source_type(cname)
        platform = row["platform"] or ""
        account_id = str(row["account_id"] or "")

        result = resolve_optimizer(
            campaign_name=cname,
            source_type=source_type,
            matcher=matcher,
        )

        match_stats[result.match_source] = match_stats.get(result.match_source, 0) + 1
        position_stats[result.match_position] = position_stats.get(result.match_position, 0) + 1

        if result.match_source != MATCH_SOURCE_UNASSIGNED:
            logger.debug(
                f"[sync_optimizer] campaign={cid} → {result.optimizer_name_normalized} "
                f"(来源: {result.match_source}, 位置: {result.match_position})"
            )
        else:
            logger.info(
                f"[sync_optimizer] campaign={cid} 未识别 "
                f"(raw='{result.optimizer_name_raw}', error={result.parse_error})"
            )

        mapping = {
            "source_type": source_type,
            "platform": platform,
            "channel": "",
            "account_id": account_id,
            "campaign_id": str(cid),
            "campaign_name": cname,
            "optimizer_name_raw": result.optimizer_name_raw,
            "optimizer_name_normalized": result.optimizer_name_normalized,
            "optimizer_source": result.match_source,
            "parse_status": result.parse_status,
            "parse_error": result.parse_error,
            "optimizer_match_source": result.match_source,
            "optimizer_match_confidence": result.match_confidence,
            "optimizer_match_position": result.match_position,
        }
        seen[cid] = mapping
        if result.match_source == MATCH_SOURCE_UNASSIGNED:
            failed_count += 1

    # Step 2: 写入 campaign_optimizer_mapping
    mapping_rows = list(seen.values())
    mapping_upserted = optimizer_performance_repository.upsert_mapping_bulk(mapping_rows)
    logger.info(f"[sync_optimizer] campaign_optimizer_mapping upserted: {mapping_upserted}")

    for src, cnt in sorted(match_stats.items(), key=lambda x: -x[1]):
        logger.info(f"[sync_optimizer] 匹配来源: {src} = {cnt}")
    for pos, cnt in sorted(position_stats.items(), key=lambda x: -x[1]):
        logger.info(f"[sync_optimizer] 匹配位置: {pos} = {cnt}")

    # Step 3: 清理该日期范围内的旧 fact 数据，防止脏数据残留
    _clean_fact_daily(start_date, end_date)

    # Step 4: 聚合 fact_optimizer_daily
    fact_map: dict[tuple, dict] = {}

    for row in daily_rows:
        cid = row["campaign_id"]
        mapping = seen.get(cid)
        if not mapping:
            continue

        opt_name = mapping["optimizer_name_normalized"]
        key = (
            str(row["stat_date"]),
            mapping["source_type"],
            mapping["platform"],
            mapping.get("channel", ""),
            str(row["account_id"] or ""),
            str(row.get("country") or ""),
            opt_name,
        )

        if key not in fact_map:
            fact_map[key] = {
                "stat_date": str(row["stat_date"]),
                "source_type": mapping["source_type"],
                "platform": mapping["platform"],
                "channel": mapping.get("channel", ""),
                "account_id": str(row["account_id"] or ""),
                "country": str(row.get("country") or ""),
                "optimizer_name": opt_name,
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "installs": 0,
                "registrations": 0,
                "purchase_value": 0.0,
                "_campaign_ids": set(),
            }

        acc = fact_map[key]
        acc["spend"] += float(row.get("spend") or 0)
        acc["impressions"] += int(row.get("impressions") or 0)
        acc["clicks"] += int(row.get("clicks") or 0)
        acc["installs"] += int(row.get("installs") or 0)
        acc["registrations"] += int(row.get("registrations") or 0)
        acc["purchase_value"] += float(row.get("purchase_value") or 0)
        acc["_campaign_ids"].add(cid)

    fact_rows = []
    for acc in fact_map.values():
        acc["campaign_count"] = len(acc.pop("_campaign_ids"))
        fact_rows.append(acc)

    fact_upserted = optimizer_performance_repository.upsert_fact_daily_bulk(fact_rows)
    logger.info(f"[sync_optimizer] fact_optimizer_daily upserted: {fact_upserted}")
    logger.info(f"[sync_optimizer] 未识别: {failed_count} 条活动")

    return {
        "mapping_upserted": mapping_upserted,
        "fact_upserted": fact_upserted,
        "failed_count": failed_count,
        "match_stats": match_stats,
        "position_stats": position_stats,
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="同步优化师映射和事实表")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    result = run(args.start, args.end)
    print(result)
