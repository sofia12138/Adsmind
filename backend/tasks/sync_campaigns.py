"""
Campaign / Adgroup / Ad 数据同步任务 — 从 TikTok / Meta API 拉取 **日级** 数据写入 adpilot_biz

用法:
    python -m tasks.sync_campaigns                           # 同步昨天数据
    python -m tasks.sync_campaigns --start 2025-03-01 --end 2025-03-31
    python -m tasks.sync_campaigns --platform tiktok
    python -m tasks.sync_campaigns --platform meta
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from config import get_settings
from repositories import (
    biz_campaign_repository,
    biz_daily_report_repository,
    biz_sync_log_repository,
)
from repositories import biz_adgroup_daily_repository, biz_ad_daily_repository
from repositories import biz_adgroup_repository, biz_ad_repository
from services import sync_state
from tiktok_ads.api.client import TikTokApiError


def _date_chunks(start: str, end: str, max_days: int = 30):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    while s <= e:
        chunk_end = min(s + timedelta(days=max_days - 1), e)
        yield s.isoformat(), chunk_end.isoformat()
        s = chunk_end + timedelta(days=1)


# ═══════════════════════════════════════════════════════════
#  错误格式化 & 网络调用重试
# ═══════════════════════════════════════════════════════════
#
# Meta / TikTok 偶发网络抖动或限流（返回 5xx / 空体）会让 svc.list 抛出
# str(e) 为空的异常，落到日志只看到 "失败: " 没有上下文。这里统一兜底：
#   - _fmt_err: 优先 str(e)，为空则用 repr(e)，确保日志/落库可读
#   - _with_retry: 对单个协程做指数退避重试，最多 attempts 次

def _fmt_err(e: BaseException) -> str:
    """返回可读错误描述：str(e) 为空时降级为 repr(e)。"""
    msg = str(e).strip() if e else ""
    return msg if msg else repr(e)


async def _with_retry(coro_factory, *, attempts: int = 3, base: float = 1.0,
                      max_wait: float = 8.0, label: str = "") -> any:
    """对协程工厂执行指数退避重试。

    coro_factory: 无参 callable，每次调用返回新 coroutine（不能重用同一个
                  coroutine 对象——await 过的 coroutine 不能再 await）。
    attempts:     总尝试次数（含首次）。默认 3 = 1 次原始 + 2 次重试。
    base:         首次失败后的等待秒数。第 i 次重试等待 min(base*2^(i-1), max_wait)。
    label:        日志标识，仅用于打印。
    """
    last_exc: BaseException | None = None
    for i in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if i >= attempts:
                break
            wait = min(base * (2 ** (i - 1)), max_wait)
            logger.warning(
                f"[retry] {label or '<call>'} 第 {i}/{attempts} 次失败: "
                f"{_fmt_err(e)}，{wait:.1f}s 后重试"
            )
            await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc


# ═══════════════════════════════════════════════════════════
#  TikTok 通用日报拉取器
# ═══════════════════════════════════════════════════════════

def _tiktok_ad_list_item_ids(a: dict) -> tuple[str, str, str]:
    """从 ad/get 单条解析 (ad_id, campaign_id, adgroup_id)。

    不同账户 / API 版本字段可能落在顶层或 creatives[0]；部分响应缺少 adgroup_id，
    会导致回传表 adset 为空、前端无法展开广告组层级。
    """
    ad_id = str(
        a.get("ad_id")
        or a.get("advertiser_ad_id")
        or ""
    ).strip()
    cid = str(a.get("campaign_id") or "").strip()
    agid = str(
        a.get("adgroup_id")
        or a.get("ad_group_id")
        or ""
    ).strip()
    cr = a.get("creatives")
    if isinstance(cr, list) and cr:
        c0 = cr[0] if isinstance(cr[0], dict) else {}
        if not ad_id:
            ad_id = str(c0.get("ad_id") or "").strip()
        if not agid:
            agid = str(c0.get("adgroup_id") or c0.get("ad_group_id") or "").strip()
        if not cid:
            cid = str(c0.get("campaign_id") or "").strip()
    return ad_id, cid, agid


async def _sync_tiktok_report_level(
    client, advertiser_id: str,
    data_level: str, id_dim: str,
    start_date: str, end_date: str,
    name_lookup: dict[str, str],
    parent_lookup: dict[str, dict] | None = None,
    campaign_name_lookup: dict[str, str] | None = None,
    adgroup_name_lookup: dict[str, str] | None = None,
):
    """通用 TikTok 报表拉取：按 30 天分段、带 stat_time_day 维度
    
    parent_lookup: {entity_id: {"campaign_id": ..., "adgroup_id": ...}}
    campaign_name_lookup: {campaign_id: campaign_name}
    adgroup_name_lookup: {adgroup_id: adgroup_name}
    """
    metrics_core = [
        "spend", "impressions", "clicks", "conversion",
        "complete_payment", "total_complete_payment_rate",
        "registration",
    ]
    metrics_extended = metrics_core + [
        "value_per_complete_payment", "total_purchase_value",
        "subscribe", "on_web_subscribe", "total_subscribe", "total_subscribe_value",
    ]
    current_metrics = list(metrics_extended)
    metrics_dropped_extended = False
    all_rows: list[dict] = []
    parent_lookup = parent_lookup or {}
    campaign_name_lookup = campaign_name_lookup or {}
    adgroup_name_lookup = adgroup_name_lookup or {}

    # AUCTION_AD：在 dimensions 中同时带上 campaign_id / adgroup_id / ad_id，
    # 避免仅依赖 ad/get 的 parent_lookup（部分响应缺 adgroup_id 时报表行 adset 全空）。
    use_ad_multi_dim = data_level == "AUCTION_AD" and id_dim == "ad_id"
    dim_multi = (
        ["campaign_id", "adgroup_id", "ad_id", "stat_time_day"] if use_ad_multi_dim else None
    )
    dim_simple = [id_dim, "stat_time_day"]

    for chunk_start, chunk_end in _date_chunks(start_date, end_date, max_days=30):
        dim_list = list(dim_multi) if dim_multi else list(dim_simple)
        dim_fallback_used = False
        page = 1
        while True:
            params = {
                "advertiser_id": advertiser_id,
                "report_type": "BASIC",
                "data_level": data_level,
                "dimensions": json.dumps(dim_list),
                "metrics": json.dumps(current_metrics),
                "start_date": chunk_start,
                "end_date": chunk_end,
                "page": page,
                "page_size": 200,
            }
            try:
                resp = await client.get("report/integrated/get/", params)
            except TikTokApiError as e:
                if use_ad_multi_dim and not dim_fallback_used:
                    logger.warning(
                        f"[TikTok] report/integrated/get 多维度广告报表失败 "
                        f"advertiser={advertiser_id} dims={dim_list}: {e}；回退为 {dim_simple}"
                    )
                    dim_list = list(dim_simple)
                    dim_fallback_used = True
                    continue
                if (
                    not metrics_dropped_extended
                    and current_metrics != metrics_core
                ):
                    logger.warning(
                        f"[TikTok] report/integrated/get 扩展指标被拒绝 "
                        f"advertiser={advertiser_id}: {e}；回退为核心指标 {metrics_core}"
                    )
                    current_metrics = list(metrics_core)
                    metrics_dropped_extended = True
                    continue
                raise
            items = resp.get("list", [])
            if not items:
                break

            for item in items:
                dims = item.get("dimensions", {})
                m = item.get("metrics", {})
                entity_id = str(dims.get(id_dim, ""))
                stat_day = (dims.get("stat_time_day", "") or "")[:10] or chunk_start

                row = {
                    "platform": "tiktok",
                    "account_id": advertiser_id,
                    "stat_date": stat_day,
                    "spend": float(m.get("spend", 0) or 0),
                    "impressions": int(m.get("impressions", 0) or 0),
                    "clicks": int(m.get("clicks", 0) or 0),
                    "installs": 0,
                    "conversions": int(m.get("conversion", 0) or 0),
                    "revenue": float(m.get("complete_payment", 0) or 0),
                    "registrations": int(m.get("registration", 0) or 0),  # App 内注册数
                    # complete_payment 在 TikTok 中是「购买次数」（int），可作为内购数
                    "purchase_count": int(float(m.get("complete_payment", 0) or 0)),
                    "raw_json": item,
                }

                if data_level == "AUCTION_CAMPAIGN":
                    row["campaign_id"] = entity_id
                    row["campaign_name"] = name_lookup.get(entity_id, "")
                elif data_level == "AUCTION_ADGROUP":
                    row["adgroup_id"] = entity_id
                    row["adgroup_name"] = name_lookup.get(entity_id, "")
                    parent = parent_lookup.get(entity_id, {})
                    cid = parent.get("campaign_id", "")
                    row["campaign_id"] = cid
                    row["campaign_name"] = campaign_name_lookup.get(cid, "")
                elif data_level == "AUCTION_AD":
                    row["ad_id"] = entity_id
                    row["ad_name"] = name_lookup.get(entity_id, "")
                    cid = str(
                        dims.get("campaign_id") or dims.get("campaignId") or ""
                    ).strip()
                    agid = str(
                        dims.get("adgroup_id")
                        or dims.get("ad_group_id")
                        or dims.get("adGroupId")
                        or ""
                    ).strip()
                    if not cid or not agid:
                        parent = parent_lookup.get(entity_id, {})
                        cid = cid or str(parent.get("campaign_id", "") or "").strip()
                        agid = agid or str(parent.get("adgroup_id", "") or "").strip()
                    row["campaign_id"] = cid
                    row["campaign_name"] = campaign_name_lookup.get(cid, "")
                    row["adgroup_id"] = agid
                    row["adgroup_name"] = adgroup_name_lookup.get(agid, "")

                all_rows.append(row)

            page_total = resp.get("page_info", {}).get("total_number", 0)
            if page * 200 >= page_total:
                break
            page += 1

    return all_rows


# ═══════════════════════════════════════════════════════════
#  TikTok 同步
# ═══════════════════════════════════════════════════════════

async def sync_tiktok_campaigns(advertiser_id: str,
                                start_date: str, end_date: str,
                                access_token: str | None = None):
    from tiktok_ads.api.campaign import CampaignService
    from tiktok_ads.api.client import TikTokClient

    # 阶段 2：未显式传 access_token 时由 client 内部走加密凭证服务
    client = (TikTokClient(access_token=access_token, account_id=advertiser_id)
              if access_token else TikTokClient(account_id=advertiser_id))
    svc = CampaignService(advertiser_id, client=client)

    # 1) Campaign 列表
    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_campaigns", platform="tiktok", account_id=advertiser_id)
    try:
        page = 1
        all_campaigns: list[dict] = []
        while True:
            resp = await svc.list(page=page, page_size=100)
            items = resp.get("list", [])
            if not items:
                break
            all_campaigns.extend(items)
            total = resp.get("page_info", {}).get("total_number", 0)
            if len(all_campaigns) >= total:
                break
            page += 1

        rows = [{
            "platform": "tiktok", "account_id": advertiser_id,
            "campaign_id": str(c.get("campaign_id", "")),
            "campaign_name": c.get("campaign_name", ""),
            "objective": c.get("objective_type", ""), "buying_type": "",
            "status": c.get("operation_status", c.get("status", "")),
            "is_active": c.get("operation_status") == "ENABLE",
            "raw_json": c,
        } for c in all_campaigns]
        affected = biz_campaign_repository.upsert_batch(rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(rows)} 个 campaign")
        logger.info(f"[TikTok] campaign 列表同步完成: {len(rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] campaign 列表同步失败: {err}")
        sync_state.set_error("structure", f"[TikTok] {advertiser_id} campaigns: {err}")
        raise

    campaign_map = {str(c.get("campaign_id")): c.get("campaign_name", "") for c in all_campaigns}

    # 2) Campaign 日报（仅写入 biz 日报表；回传口径表与 Meta 一致，只在 **Ad 粒度** 写入，避免层级 SUM 膨胀且保证前端树形层级可展开）
    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_campaign_daily", platform="tiktok", account_id=advertiser_id, sync_date=start_date)
    try:
        report_rows = await _with_retry(
            lambda: _sync_tiktok_report_level(
                client, advertiser_id, "AUCTION_CAMPAIGN", "campaign_id",
                start_date, end_date, campaign_map),
            label=f"[TikTok] {advertiser_id} campaign 日报",
        )
        affected = biz_daily_report_repository.upsert_batch(report_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"campaign 日报 {len(report_rows)} 条")
        logger.info(f"[TikTok] campaign 日报同步完成: {len(report_rows)} 条")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] campaign 日报同步失败: {err}")
        sync_state.set_error("reports", f"[TikTok] {advertiser_id} campaign 日报: {err}")

    # 3) Adgroup 列表 → 入库 + 名称映射
    from tiktok_ads.api.adgroup import AdGroupService
    ag_svc = AdGroupService(advertiser_id, client=client)

    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_adgroups", platform="tiktok", account_id=advertiser_id)
    all_adgroups: list[dict] = []
    try:
        page = 1
        while True:
            resp = await ag_svc.list(page=page, page_size=100)
            items = resp.get("list", [])
            if not items:
                break
            all_adgroups.extend(items)
            total = resp.get("page_info", {}).get("total_number", 0)
            if len(all_adgroups) >= total:
                break
            page += 1

        ag_rows = [{
            "platform": "tiktok", "account_id": advertiser_id,
            "campaign_id": str(ag.get("campaign_id", "")),
            "adgroup_id": str(ag.get("adgroup_id", "")),
            "adgroup_name": ag.get("adgroup_name", ""),
            "status": ag.get("operation_status", ag.get("status", "")),
            "is_active": ag.get("operation_status") == "ENABLE",
            "raw_json": ag,
        } for ag in all_adgroups]
        affected = biz_adgroup_repository.upsert_batch(ag_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(ag_rows)} 个 adgroup")
        logger.info(f"[TikTok] adgroup 列表同步完成: {len(ag_rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] adgroup 列表同步失败: {err}")
        sync_state.set_error("structure", f"[TikTok] {advertiser_id} adgroups: {err}")

    adgroup_name_map = {str(ag.get("adgroup_id")): ag.get("adgroup_name", "") for ag in all_adgroups}
    adgroup_parent_map = {str(ag.get("adgroup_id")): {"campaign_id": str(ag.get("campaign_id", ""))} for ag in all_adgroups}

    # 4) Adgroup 日报
    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_adgroup_daily", platform="tiktok", account_id=advertiser_id, sync_date=start_date)
    try:
        adgroup_rows = await _with_retry(
            lambda: _sync_tiktok_report_level(
                client, advertiser_id, "AUCTION_ADGROUP", "adgroup_id",
                start_date, end_date, adgroup_name_map,
                parent_lookup=adgroup_parent_map,
                campaign_name_lookup=campaign_map),
            label=f"[TikTok] {advertiser_id} adgroup 日报",
        )
        affected = biz_adgroup_daily_repository.upsert_batch(adgroup_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"adgroup 日报 {len(adgroup_rows)} 条")
        logger.info(f"[TikTok] adgroup 日报同步完成: {len(adgroup_rows)} 条")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] adgroup 日报同步失败: {err}")
        sync_state.set_error("reports", f"[TikTok] {advertiser_id} adgroup 日报: {err}")

    # 5) Ad 列表 → 入库 + 名称映射
    from tiktok_ads.api.ad import AdService
    ad_svc = AdService(advertiser_id, client=client)

    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_ads", platform="tiktok", account_id=advertiser_id)
    all_ads: list[dict] = []
    try:
        page = 1
        while True:
            resp = await ad_svc.list(page=page, page_size=100)
            items = resp.get("list", [])
            if not items:
                break
            all_ads.extend(items)
            total = resp.get("page_info", {}).get("total_number", 0)
            if len(all_ads) >= total:
                break
            page += 1

        ad_db_rows = []
        for a in all_ads:
            aid, cid, agid = _tiktok_ad_list_item_ids(a)
            if not aid:
                continue
            nm = a.get("ad_name") or a.get("advertiser_ad_name") or ""
            ad_db_rows.append({
                "platform": "tiktok", "account_id": advertiser_id,
                "campaign_id": cid,
                "adgroup_id": agid,
                "ad_id": aid,
                "ad_name": nm,
                "status": a.get("operation_status", a.get("status", "")),
                "is_active": a.get("operation_status") == "ENABLE",
                "raw_json": a,
            })
        affected = biz_ad_repository.upsert_batch(ad_db_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(ad_db_rows)} 个 ad")
        logger.info(f"[TikTok] ad 列表同步完成: {len(ad_db_rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] ad 列表同步失败: {err}")
        sync_state.set_error("structure", f"[TikTok] {advertiser_id} ads: {err}")

    ad_name_map: dict[str, str] = {}
    ad_parent_map: dict[str, dict] = {}
    for a in all_ads:
        aid, cid, agid = _tiktok_ad_list_item_ids(a)
        if not aid:
            continue
        ad_name_map[aid] = str(a.get("ad_name") or a.get("advertiser_ad_name") or "")
        ad_parent_map[aid] = {"campaign_id": cid, "adgroup_id": agid}

    # 6) Ad 日报
    log_id = biz_sync_log_repository.create(task_name="sync_tiktok_ad_daily", platform="tiktok", account_id=advertiser_id, sync_date=start_date)
    try:
        ad_rows = await _with_retry(
            lambda: _sync_tiktok_report_level(
                client, advertiser_id, "AUCTION_AD", "ad_id",
                start_date, end_date, ad_name_map,
                parent_lookup=ad_parent_map,
                campaign_name_lookup=campaign_map,
                adgroup_name_lookup=adgroup_name_map),
            label=f"[TikTok] {advertiser_id} ad 日报",
        )
        affected = biz_ad_daily_repository.upsert_batch(ad_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"ad 日报 {len(ad_rows)} 条")
        logger.info(f"[TikTok] ad 日报同步完成: {len(ad_rows)} 条")
        from repositories import returned_conversion_repository
        for r in ad_rows:
            ret = _tiktok_row_to_returned_row(r, advertiser_id)
            try:
                returned_conversion_repository.upsert(**ret)
            except Exception as e_ret:
                logger.warning(f"[TikTok] returned_conversion upsert(ad) 失败: {_fmt_err(e_ret)}")
        if ad_rows:
            try:
                n = returned_conversion_repository.delete_tiktok_campaign_granularity_returned_rows(
                    advertiser_id, start_date, end_date,
                )
                if n:
                    logger.info(f"[TikTok] 清理历史 campaign 粒度回传行 {n} 条（同期已有 ad 粒度数据）")
            except Exception as e_del:
                logger.warning(f"[TikTok] 清理 campaign 粒度回传行失败: {_fmt_err(e_del)}")
        # 日报模块完成标记（TikTok Ad 日报为最后一步）
        sync_state.set_done("reports")
        sync_state.set_done("structure")
        sync_state.set_done("returned")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[TikTok] ad 日报同步失败: {err}")
        sync_state.set_error("reports", f"[TikTok] {advertiser_id} ad 日报: {err}")
        sync_state.set_error("returned", f"[TikTok] {advertiser_id} ad 日报: {err}")


# ═══════════════════════════════════════════════════════════
#  Meta 通用 Insights 拉取器
# ═══════════════════════════════════════════════════════════

async def _fetch_meta_insights_paged(client, ad_account_id: str,
                                     start_date: str, end_date: str,
                                     level: str, fields: str) -> list[dict]:
    import httpx
    params = {
        "fields": fields,
        "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        "time_increment": "1",
        "level": level,
        "limit": 500,
        "use_account_attribution_setting": "true",
    }
    all_data: list[dict] = []
    resp = await client.get(f"{ad_account_id}/insights", params)
    all_data.extend(resp.get("data", []))

    while resp.get("paging", {}).get("next"):
        next_url = resp["paging"]["next"]
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(next_url)
            resp = r.json()
            if "error" in resp:
                break
            all_data.extend(resp.get("data", []))
    return all_data


def _parse_meta_actions(raw_list: list | None) -> dict[str, int]:
    """
    Meta actions / action_values 字段为数组结构，需按 action_type 精确提取。
    返回 {action_type: int(value)} 字典。不要直接按 key 读取，避免漏值或解析错误。
    """
    if not raw_list:
        return {}
    result: dict[str, int] = {}
    for entry in raw_list:
        if isinstance(entry, dict):
            atype = entry.get("action_type", "")
            if atype:
                result[atype] = int(float(entry.get("value", 0) or 0))
    return result


def _parse_meta_action_values(raw_list: list | None) -> dict[str, float]:
    """
    Meta action_values 字段为数组结构，按 action_type 精确提取金额（float）。
    用于提取 purchase 金额（purchase_value_returned）。
    """
    if not raw_list:
        return {}
    result: dict[str, float] = {}
    for entry in raw_list:
        if isinstance(entry, dict):
            atype = entry.get("action_type", "")
            if atype:
                result[atype] = float(entry.get("value", 0.0) or 0.0)
    return result


def _extract_subscribe_value(item: dict) -> float:
    """从 Meta Insights 的 conversion_values 字段提取订阅价值。

    Ads Manager "订阅价值" 列来自 conversion_values（非 action_values）。
    优先取 subscribe_total（跨渠道汇总），降级取 subscribe_website。
    """
    raw = item.get("conversion_values")
    if not raw:
        return 0.0
    cv: dict[str, float] = {}
    for entry in raw:
        if isinstance(entry, dict):
            atype = entry.get("action_type", "")
            if atype:
                cv[atype] = float(entry.get("value", 0.0) or 0.0)
    return cv.get("subscribe_total", 0.0) or cv.get("subscribe_website", 0.0)


def _extract_subscribe_count(item: dict) -> int:
    """从 Meta Insights 的 conversions 字段提取订阅次数。

    与 _extract_subscribe_value 对应：conversions 数组结构与 actions 相同，
    存储次数（int），优先取 subscribe_total，降级取 subscribe_website。
    """
    raw = item.get("conversions")
    if not raw:
        return 0
    cnt: dict[str, int] = {}
    for entry in raw:
        if isinstance(entry, dict):
            atype = entry.get("action_type", "")
            if atype:
                cnt[atype] = int(float(entry.get("value", 0) or 0))
    return cnt.get("subscribe_total", 0) or cnt.get("subscribe_website", 0)


def _meta_insight_to_row(item: dict, ad_account_id: str, level: str) -> dict:
    # actions / action_values 均为数组，必须通过 _parse_meta_* 函数提取
    actions = _parse_meta_actions(item.get("actions"))
    action_values = _parse_meta_action_values(item.get("action_values"))

    row = {
        "platform": "meta",
        "account_id": ad_account_id,
        "campaign_id": str(item.get("campaign_id", "")),
        "campaign_name": item.get("campaign_name", ""),
        "stat_date": item.get("date_start", ""),
        "spend": float(item.get("spend", 0) or 0),
        "impressions": int(item.get("impressions", 0) or 0),
        "clicks": int(item.get("clicks", 0) or 0),
        "installs": actions.get("mobile_app_install", 0),
        "conversions": actions.get("offsite_conversion", 0) + actions.get("purchase", 0),
        "revenue": 0,
        "raw_json": item,
    }
    if level in ("adset", "ad"):
        row["adgroup_id"] = str(item.get("adset_id", ""))
        row["adgroup_name"] = item.get("adset_name", "")
    if level == "ad":
        row["ad_id"] = str(item.get("ad_id", ""))
        row["ad_name"] = item.get("ad_name", "")
    return row


def _meta_insight_to_returned_row(item: dict, ad_account_id: str, level: str) -> dict:
    """
    将 Meta Insights 数据映射到 ad_returned_conversion_daily 回传口径行。

    字段映射说明（对应 PLATFORM_FIELD_SUPPORT["meta"]）：
    - registrations_returned:   omni_complete_registration（优先）or complete_registration
                                  omni 是跨渠道汇总，已包含 app 注册，不与 complete 相加
    - purchase_value_returned:  omni_purchase（优先）or purchase，来自 action_values 数组（金额）
    - purchase_count_returned:  omni_purchase（优先）or purchase，来自 actions 数组（次数）
    - subscribe_value_returned: 来自 conversion_values 中的 subscribe_total / subscribe_website
                                  （Ads Manager "订阅价值"列的实际数据源）
    - subscribe_count_returned: 来自 conversions 中的 subscribe_total / subscribe_website（次数）
    - d1_value_returned:        0（Meta Insights 无 D1 cohort 拆分）
    - installs:                 actions 数组中 action_type=mobile_app_install 的 value
    """
    actions = _parse_meta_actions(item.get("actions"))
    action_values = _parse_meta_action_values(item.get("action_values"))

    subscribe_val = _extract_subscribe_value(item)
    subscribe_cnt = _extract_subscribe_count(item)

    returned: dict = {
        "stat_date":                item.get("date_start", ""),
        "media_source":             "meta",
        "account_id":               ad_account_id,
        "campaign_id":              str(item.get("campaign_id", "")),
        "campaign_name":            item.get("campaign_name", ""),
        "adset_id":                 "",
        "adset_name":               "",
        "ad_id":                    "",
        "ad_name":                  "",
        "country":                  "",
        "platform":                 "",
        "impressions":              int(item.get("impressions", 0) or 0),
        "clicks":                   int(item.get("clicks", 0) or 0),
        "installs":                 actions.get("mobile_app_install", 0),
        "spend":                    float(item.get("spend", 0) or 0),
        "registrations_returned":   (
            actions.get("omni_complete_registration", 0)
            or actions.get("complete_registration", 0)
        ),
        "purchase_value_returned":  (
            action_values.get("omni_purchase", 0.0)
            or action_values.get("purchase", 0.0)
        ),
        "purchase_count_returned":  (
            actions.get("omni_purchase", 0)
            or actions.get("purchase", 0)
        ),
        "subscribe_value_returned":    subscribe_val,
        "subscribe_count_returned":    subscribe_cnt,
        # Meta 不支持：无 D1 cohort 拆分，固定为 0
        "d1_value_returned":           0.0,
        # D0 Cohort：Meta 标准 Insights API 无法拆分 D0 cohort，固定为 0
        "d0_registrations_returned":   0,
        "d0_purchase_value_returned":  0.0,
        "d0_subscribe_value_returned": 0.0,
        "raw_payload":                 item,
    }
    if level in ("adset", "ad"):
        returned["adset_id"]   = str(item.get("adset_id", ""))
        returned["adset_name"] = item.get("adset_name", "")
    if level == "ad":
        returned["ad_id"]   = str(item.get("ad_id", ""))
        returned["ad_name"] = item.get("ad_name", "")
    return returned


def _tiktok_report_metrics(row: dict) -> dict:
    """从日报行的 raw_json 中取 TikTok report/integrated/get 的 metrics 字典。"""
    payload = row.get("raw_json")
    if isinstance(payload, dict):
        m = payload.get("metrics")
        if isinstance(m, dict):
            return m
    return {}


def _tiktok_row_to_returned_row(row: dict, advertiser_id: str) -> dict:
    """
    将 TikTok 日报行映射到 ad_returned_conversion_daily 回传口径行。

    字段映射说明（对应 PLATFORM_FIELD_SUPPORT["tiktok"]）：
    - registrations_returned:   registration 指标（App 内注册等）
    - purchase_count_returned:  complete_payment（完成支付次数）
    - purchase_value_returned:  优先 value_per_complete_payment × complete_payment；
                                否则用 total_purchase_value（按计费时间口径，可能非零）
    - subscribe_count_returned: subscribe + on_web_subscribe；若均为 0 则用 total_subscribe
    - subscribe_value_returned: total_subscribe_value（无则 0）
    - d1_value_returned:        固定为 0
    """
    m = _tiktok_report_metrics(row)
    cp_cnt = int(float(m.get("complete_payment", 0) or 0))
    vpc = float(m.get("value_per_complete_payment", 0) or 0)
    if cp_cnt > 0 and vpc > 0:
        purchase_value = round(cp_cnt * vpc, 4)
    else:
        purchase_value = round(float(m.get("total_purchase_value", 0) or 0), 4)

    sub_cnt = int(m.get("subscribe", 0) or 0) + int(m.get("on_web_subscribe", 0) or 0)
    if sub_cnt <= 0:
        sub_cnt = int(m.get("total_subscribe", 0) or 0)
    sub_val = round(float(m.get("total_subscribe_value", 0) or 0), 4)

    return {
        "stat_date":                row.get("stat_date", ""),
        "media_source":             "tiktok",
        "account_id":               advertiser_id,
        "campaign_id":              row.get("campaign_id", ""),
        "campaign_name":            row.get("campaign_name", ""),
        "adset_id":                 row.get("adgroup_id", ""),
        "adset_name":               row.get("adgroup_name", ""),
        "ad_id":                    row.get("ad_id", ""),
        "ad_name":                  row.get("ad_name", ""),
        "country":                  "",
        "platform":                 "",
        "impressions":              int(row.get("impressions", 0) or 0),
        "clicks":                   int(row.get("clicks", 0) or 0),
        "installs":                 int(row.get("installs", 0) or 0),
        "spend":                    float(row.get("spend", 0) or 0),
        "registrations_returned":   int(row.get("registrations", 0) or 0),
        "purchase_value_returned":     float(purchase_value),
        "purchase_count_returned":     int(row.get("purchase_count", 0) or 0),
        "subscribe_value_returned":    float(sub_val),
        "subscribe_count_returned":    int(sub_cnt),
        "d1_value_returned":           0.0,
        "d0_registrations_returned":   0,
        "d0_purchase_value_returned":  0.0,
        "d0_subscribe_value_returned": 0.0,
        "raw_payload":                 row.get("raw_json"),
    }


# ═══════════════════════════════════════════════════════════
#  Meta 同步
# ═══════════════════════════════════════════════════════════

async def sync_meta_campaigns(ad_account_id: str,
                              start_date: str, end_date: str,
                              access_token: str | None = None):
    from meta_ads.api.campaigns import MetaCampaignService
    from meta_ads.api.client import MetaClient

    # 阶段 2：未显式传 access_token 时由 client 内部走加密凭证服务
    client = (MetaClient(access_token=access_token, account_id=ad_account_id)
              if access_token else MetaClient(account_id=ad_account_id))
    svc = MetaCampaignService(ad_account_id, client=client)

    # 1) Campaign 列表
    log_id = biz_sync_log_repository.create(task_name="sync_meta_campaigns", platform="meta", account_id=ad_account_id)
    try:
        resp = await _with_retry(
            lambda: svc.list(limit=200),
            label=f"[Meta] {ad_account_id}/campaigns",
        )
        items = resp.get("data", [])
        rows = [{
            "platform": "meta", "account_id": ad_account_id,
            "campaign_id": str(c.get("id", "")),
            "campaign_name": c.get("name", ""),
            "objective": c.get("objective", ""),
            "buying_type": c.get("buying_type", ""),
            "status": c.get("effective_status", c.get("status", "")),
            "is_active": c.get("effective_status") == "ACTIVE",
            "raw_json": c,
        } for c in items]
        affected = biz_campaign_repository.upsert_batch(rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(rows)} 个 campaign")
        logger.info(f"[Meta] campaign 列表同步完成: {len(rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] campaign 列表同步失败: {err}")
        sync_state.set_error("structure", f"[Meta] {ad_account_id} campaigns: {err}")
        raise

    # 2) Adset 列表 → 入库
    from meta_ads.api.adsets import MetaAdSetService
    adset_svc = MetaAdSetService(ad_account_id, client=client)

    log_id = biz_sync_log_repository.create(task_name="sync_meta_adsets", platform="meta", account_id=ad_account_id)
    all_adsets: list[dict] = []
    try:
        resp = await _with_retry(
            lambda: adset_svc.list(limit=200),
            label=f"[Meta] {ad_account_id}/adsets",
        )
        all_adsets = resp.get("data", [])
        ag_rows = [{
            "platform": "meta", "account_id": ad_account_id,
            "campaign_id": str(a.get("campaign_id", "")),
            "adgroup_id": str(a.get("id", "")),
            "adgroup_name": a.get("name", ""),
            "status": a.get("effective_status", a.get("status", "")),
            "is_active": a.get("effective_status") == "ACTIVE",
            "raw_json": a,
        } for a in all_adsets]
        affected = biz_adgroup_repository.upsert_batch(ag_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(ag_rows)} 个 adset")
        logger.info(f"[Meta] adset 列表同步完成: {len(ag_rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] adset 列表同步失败: {err}")
        sync_state.set_error("structure", f"[Meta] {ad_account_id} adsets: {err}")

    # 3) Ad 列表 → 入库
    from meta_ads.api.ads import MetaAdService
    ad_svc = MetaAdService(ad_account_id, client=client)

    log_id = biz_sync_log_repository.create(task_name="sync_meta_ads", platform="meta", account_id=ad_account_id)
    all_meta_ads: list[dict] = []
    try:
        resp = await _with_retry(
            lambda: ad_svc.list(limit=200),
            label=f"[Meta] {ad_account_id}/ads",
        )
        all_meta_ads = resp.get("data", [])
        ad_db_rows = [{
            "platform": "meta", "account_id": ad_account_id,
            "campaign_id": str(a.get("campaign_id", "")),
            "adgroup_id": str(a.get("adset_id", "")),
            "ad_id": str(a.get("id", "")),
            "ad_name": a.get("name", ""),
            "status": a.get("effective_status", a.get("status", "")),
            "is_active": a.get("effective_status") == "ACTIVE",
            "raw_json": a,
        } for a in all_meta_ads]
        affected = biz_ad_repository.upsert_batch(ad_db_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"同步 {len(ad_db_rows)} 个 ad")
        logger.info(f"[Meta] ad 列表同步完成: {len(ad_db_rows)} 个")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] ad 列表同步失败: {err}")
        sync_state.set_error("structure", f"[Meta] {ad_account_id} ads: {err}")

    # action_values: purchase 金额; conversion_values: subscribe 金额(Ads Manager "订阅价值"列)
    campaign_fields = "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values,conversions,conversion_values"
    adset_fields = "campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,actions,action_values,conversions,conversion_values"
    ad_fields = "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,clicks,actions,action_values,conversions,conversion_values"

    from repositories import returned_conversion_repository

    # 4) Campaign 日报
    log_id = biz_sync_log_repository.create(task_name="sync_meta_campaign_daily", platform="meta", account_id=ad_account_id, sync_date=start_date)
    try:
        data = await _with_retry(
            lambda: _fetch_meta_insights_paged(client, ad_account_id, start_date, end_date, "campaign", campaign_fields),
            label=f"[Meta] {ad_account_id} campaign insights",
        )
        report_rows = [_meta_insight_to_row(item, ad_account_id, "campaign") for item in data]
        affected = biz_daily_report_repository.upsert_batch(report_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"campaign 日报 {len(report_rows)} 条")
        logger.info(f"[Meta] campaign 日报同步完成: {len(report_rows)} 条")
        # 回传口径表只在 ad 级别（最细粒度）写入，避免 campaign/adset/ad 三级重复导致 SUM 膨胀
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] campaign 日报同步失败: {err}")
        sync_state.set_error("reports", f"[Meta] {ad_account_id} campaign 日报: {err}")

    # 5) Adset 日报
    log_id = biz_sync_log_repository.create(task_name="sync_meta_adset_daily", platform="meta", account_id=ad_account_id, sync_date=start_date)
    try:
        data = await _with_retry(
            lambda: _fetch_meta_insights_paged(client, ad_account_id, start_date, end_date, "adset", adset_fields),
            label=f"[Meta] {ad_account_id} adset insights",
        )
        adset_rows = [_meta_insight_to_row(item, ad_account_id, "adset") for item in data]
        affected = biz_adgroup_daily_repository.upsert_batch(adset_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"adset 日报 {len(adset_rows)} 条")
        logger.info(f"[Meta] adset 日报同步完成: {len(adset_rows)} 条")
        # 回传口径表只在 ad 级别写入，此处不再重复写入 adset 级别
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] adset 日报同步失败: {err}")
        sync_state.set_error("reports", f"[Meta] {ad_account_id} adset 日报: {err}")

    # 6) Ad 日报
    log_id = biz_sync_log_repository.create(task_name="sync_meta_ad_daily", platform="meta", account_id=ad_account_id, sync_date=start_date)
    try:
        data = await _with_retry(
            lambda: _fetch_meta_insights_paged(client, ad_account_id, start_date, end_date, "ad", ad_fields),
            label=f"[Meta] {ad_account_id} ad insights",
        )
        ad_rows = [_meta_insight_to_row(item, ad_account_id, "ad") for item in data]
        affected = biz_ad_daily_repository.upsert_batch(ad_rows)
        biz_sync_log_repository.finish(log_id, status="success", rows_affected=affected, message=f"ad 日报 {len(ad_rows)} 条")
        logger.info(f"[Meta] ad 日报同步完成: {len(ad_rows)} 条")
        # 回传口径表只在 ad 级别写入（最细粒度），campaign/adset 级别不再写入以避免 SUM 膨胀
        for item in data:
            ret = _meta_insight_to_returned_row(item, ad_account_id, "ad")
            try:
                returned_conversion_repository.upsert(**ret)
            except Exception as e_ret:
                logger.warning(f"[Meta] returned_conversion upsert(ad) 失败: {_fmt_err(e_ret)}")
        # 日报 + 结构完成标记
        sync_state.set_done("reports")
        sync_state.set_done("structure")
        sync_state.set_done("returned")
    except Exception as e:
        err = _fmt_err(e)
        biz_sync_log_repository.finish(log_id, status="failed", message=err)
        logger.error(f"[Meta] ad 日报同步失败: {err}")
        sync_state.set_error("reports", f"[Meta] {ad_account_id} ad 日报: {err}")
        sync_state.set_error("returned", f"[Meta] {ad_account_id} ad 日报: {err}")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

async def run(platform: str | None = None,
              start_date: str | None = None, end_date: str | None = None):
    settings = get_settings()

    if not start_date:
        yesterday = date.today() - timedelta(days=1)
        start_date = yesterday.strftime("%Y-%m-%d")
    if not end_date:
        end_date = start_date

    date_range = f"{start_date} ~ {end_date}"
    logger.info(f"开始同步数据: platform={platform or 'all'}, range={date_range}")

    # 标记各模块开始运行
    for mod in ("structure", "reports", "returned"):
        sync_state.set_running(mod, True, date_range=date_range)

    try:
        from repositories import biz_account_repository
        db_accounts = biz_account_repository.list_active()
    except Exception:
        db_accounts = []

    synced_any = False

    # 新账号首次同步回填天数
    FIRST_SYNC_DAYS = 30

    if db_accounts:
        for acct in db_accounts:
            p = acct["platform"]
            if platform and p != platform:
                continue
            aid = acct["account_id"]
            # 阶段 2：先走加密凭证服务（加密表 → 旧明文兼容 → .env 兜底）
            # 仍保留 acct["access_token"] 兼容，但 resolve_access_token 内部已经会回退到这一层。
            from services.credential_service import resolve_access_token as _resolve
            token = _resolve(p, account_id=aid) or acct.get("access_token")

            # 首次同步（last_synced_at 为 NULL）自动回填近 N 天
            acct_start = start_date
            acct_end   = end_date
            if not acct.get("last_synced_at"):
                yesterday = date.today() - timedelta(days=1)
                acct_start = (date.today() - timedelta(days=FIRST_SYNC_DAYS)).isoformat()
                acct_end   = yesterday.isoformat()
                logger.info(
                    f"[首次同步] {p}/{aid} last_synced_at=NULL，"
                    f"自动回填 {FIRST_SYNC_DAYS} 天: {acct_start} ~ {acct_end}"
                )

            try:
                if p == "tiktok":
                    await sync_tiktok_campaigns(aid, acct_start, acct_end, access_token=token)
                elif p == "meta":
                    await sync_meta_campaigns(aid, acct_start, acct_end, access_token=token)
                biz_account_repository.update_last_synced(acct["id"])
                synced_any = True
            except Exception as e:
                err = _fmt_err(e)
                logger.error(f"同步账户 {p}/{aid} 失败: {err}")
                # 账户级别失败时显式标记三个模块（structure/reports/returned）出错
                # 这样前端的同步状态指示能立即变红，而不是停在"运行中"
                for mod in ("structure", "reports", "returned"):
                    sync_state.set_error(mod, f"{p}/{aid}: {err}")

    if not synced_any:
        if platform in (None, "tiktok"):
            advertiser_id = settings.tiktok_advertiser_id
            if advertiser_id:
                await sync_tiktok_campaigns(advertiser_id, start_date, end_date)
            else:
                logger.warning("TIKTOK_ADVERTISER_ID 未配置，跳过 TikTok 同步")
        if platform in (None, "meta"):
            ad_account_id = settings.meta_ad_account_id
            if ad_account_id:
                await sync_meta_campaigns(ad_account_id, start_date, end_date)
            else:
                logger.warning("META_AD_ACCOUNT_ID 未配置，跳过 Meta 同步")

    logger.info("同步完成")


def main():
    parser = argparse.ArgumentParser(description="AdsMind 全量数据同步")
    parser.add_argument("--platform", choices=["tiktok", "meta"], default=None)
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()
    asyncio.run(run(platform=args.platform, start_date=args.start, end_date=args.end))


if __name__ == "__main__":
    main()
