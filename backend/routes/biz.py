"""BIZ 业务数据查询路由 — adpilot_biz 归一化数据 + 归因数据双源拼接"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from config import get_settings
from core.application import ApplicationCtx, get_current_application
from core.biz_filter import (
    filter_rows_by_account_whitelist,
    get_application_account_whitelist,
    resolve_account_filter,
)
from repositories import (
    biz_daily_report_repository,
    biz_campaign_repository,
    biz_adgroup_daily_repository,
    biz_ad_daily_repository,
    biz_adgroup_repository,
    biz_ad_repository,
)
from services import biz_attribution_service, biz_blend_service

router = APIRouter(prefix="/biz", tags=["BIZ 业务数据"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SOURCE = {"auto", "attribution", "legacy", "blend"}
_SOURCE_DESC = "数据源: auto/blend/attribution/legacy"


def _check_dates(start_date: str, end_date: str):
    if not _DATE_RE.match(start_date):
        raise HTTPException(400, f"start_date 格式错误，应为 YYYY-MM-DD，实际: {start_date}")
    if not _DATE_RE.match(end_date):
        raise HTTPException(400, f"end_date 格式错误，应为 YYYY-MM-DD，实际: {end_date}")
    if start_date > end_date:
        raise HTTPException(400, f"start_date({start_date}) 不能大于 end_date({end_date})")


def _resolve_source(source: str) -> str:
    """
    auto        → 由 env DATA_SOURCE_DEFAULT 决定（默认 blend）
    blend       → normalized 投放指标 + attribution 真值业务结果（推荐生产口径）
    attribution → 强制走纯归因表（biz_attribution_ad_daily/intraday）
    legacy      → 强制走 normalized 表（旧口径，spend 完整但 revenue 失真）
    """
    if source not in _ALLOWED_SOURCE:
        raise HTTPException(400, f"source 必须是 {_ALLOWED_SOURCE}, 实际: {source}")
    if source == "auto":
        default = (get_settings().data_source_default or "").lower()
        if default in ("blend", "attribution", "legacy"):
            return default
        return "attribution" if get_settings().attribution_primary else "legacy"
    return source


@router.get("/campaigns")
async def biz_campaigns(
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    application: ApplicationCtx = Depends(get_current_application),
):
    """返回 BIZ 库中所有 campaign（含 status / account_id / raw_json）"""
    if platform:
        rows = await asyncio.to_thread(biz_campaign_repository.list_by_platform, platform)
    else:
        rows = await asyncio.to_thread(biz_campaign_repository.list_all)
    # 阶段 4 X3-filter Round 3：list 型接口按 account_id 白名单后置过滤
    rows = filter_rows_by_account_whitelist(
        rows, get_application_account_whitelist(application)
    )
    for row in rows:
        for k in ("created_at", "updated_at"):
            if k in row and row[k] is not None:
                row[k] = str(row[k])
    return {"code": 0, "message": "ok", "data": rows, "_application_id": application.id}


@router.post("/update-status")
async def biz_update_status(
    platform: str = Query(..., description="tiktok / meta"),
    entity_type: str = Query(..., description="campaign / adgroup / ad"),
    entity_id: str = Query(..., description="实体 ID"),
    status: str = Query(..., description="新状态"),
):
    """操作成功后同步更新 BIZ 库中的 status 字段"""
    if entity_type == "campaign":
        affected = await asyncio.to_thread(biz_campaign_repository.update_status, platform, entity_id, status)
    elif entity_type == "adgroup":
        affected = await asyncio.to_thread(biz_adgroup_repository.update_status, platform, entity_id, status)
    elif entity_type == "ad":
        affected = await asyncio.to_thread(biz_ad_repository.update_status, platform, entity_id, status)
    else:
        raise HTTPException(400, f"未知 entity_type: {entity_type}")
    return {"code": 0, "message": "ok", "data": {"affected": affected}}


@router.get("/adgroups")
async def biz_adgroups(
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    application: ApplicationCtx = Depends(get_current_application),
):
    """返回 BIZ 库中所有 adgroup（含 status / account_id）"""
    if platform:
        rows = await asyncio.to_thread(biz_adgroup_repository.list_by_platform, platform)
    else:
        rows = await asyncio.to_thread(biz_adgroup_repository.list_all)
    rows = filter_rows_by_account_whitelist(
        rows, get_application_account_whitelist(application)
    )
    for row in rows:
        for k in ("created_at", "updated_at"):
            if k in row and row[k] is not None:
                row[k] = str(row[k])
    return {"code": 0, "message": "ok", "data": rows, "_application_id": application.id}


@router.get("/ads")
async def biz_ads(
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    application: ApplicationCtx = Depends(get_current_application),
):
    """返回 BIZ 库中所有 ad（含 status / account_id）"""
    if platform:
        rows = await asyncio.to_thread(biz_ad_repository.list_by_platform, platform)
    else:
        rows = await asyncio.to_thread(biz_ad_repository.list_all)
    rows = filter_rows_by_account_whitelist(
        rows, get_application_account_whitelist(application)
    )
    for row in rows:
        for k in ("created_at", "updated_at"):
            if k in row and row[k] is not None:
                row[k] = str(row[k])
    return {"code": 0, "message": "ok", "data": rows, "_application_id": application.id}


@router.get("/overview")
async def biz_overview(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    account_id: Optional[str] = Query(None, description="账户 ID 过滤"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
    application: ApplicationCtx = Depends(get_current_application),
):
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    # 阶段 4 X3-filter Round 2：应用级账号白名单守门
    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {
            "code": 0,
            "message": "ok",
            "data": {"_source": src, "_hint": flt.hint, "_application_id": application.id},
        }
    account_id = flt.account_id

    if src == "attribution":
        data = await asyncio.to_thread(
            biz_attribution_service.get_overview,
            start_date, end_date,
            platform=platform, account_id=account_id,
        )
    elif src == "blend":
        data = await asyncio.to_thread(
            biz_blend_service.get_overview,
            start_date, end_date,
            platform=platform, account_id=account_id,
        )
    else:
        data = await asyncio.to_thread(
            biz_daily_report_repository.get_overview,
            start_date, end_date,
            platform=platform, account_id=account_id,
        )
    for k, v in data.items():
        if hasattr(v, "__float__"):
            data[k] = float(v)
        elif hasattr(v, "__int__") and not isinstance(v, bool):
            data[k] = int(v)
    data["_source"] = src
    data["_application_id"] = application.id
    return {"code": 0, "message": "ok", "data": data}


@router.get("/campaign-daily")
async def biz_campaign_daily(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    campaign_name: Optional[str] = Query(None, description="模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    order_by: str = Query("stat_date"),
    order_dir: str = Query("desc"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
    application: ApplicationCtx = Depends(get_current_application),
):
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {
            "code": 0, "message": "ok",
            "data": {"list": [], "total": 0, "page": page, "page_size": page_size,
                     "_source": src, "_hint": flt.hint, "_application_id": application.id},
        }
    account_id = flt.account_id

    if src == "attribution":
        data = await asyncio.to_thread(
            biz_attribution_service.get_campaign_daily_list,
            start_date, end_date,
            platform=platform, account_id=account_id,
            campaign_name=campaign_name,
            page=page, page_size=page_size,
            order_by=order_by, order_dir=order_dir,
        )
    elif src == "blend":
        data = await asyncio.to_thread(
            biz_blend_service.get_campaign_daily_list,
            start_date, end_date,
            platform=platform, account_id=account_id,
            campaign_name=campaign_name,
            page=page, page_size=page_size,
            order_by=order_by, order_dir=order_dir,
        )
    else:
        data = await asyncio.to_thread(
            biz_daily_report_repository.get_campaign_daily_list,
            start_date, end_date,
            platform=platform, account_id=account_id,
            campaign_name=campaign_name,
            page=page, page_size=page_size,
            order_by=order_by, order_dir=order_dir,
        )
    for row in data["list"]:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    data["_source"] = src
    return {"code": 0, "message": "ok", "data": data}


@router.get("/top-campaigns")
async def biz_top_campaigns(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    metric: str = Query("spend", description="排序指标: spend/revenue/clicks/installs/conversions/roas"),
    limit: int = Query(20, ge=1, le=100),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
    application: ApplicationCtx = Depends(get_current_application),
):
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {"code": 0, "message": "ok", "data": [],
                "_source": src, "_hint": flt.hint, "_application_id": application.id}
    account_id = flt.account_id

    if src == "attribution":
        rows = await asyncio.to_thread(
            biz_attribution_service.get_top_campaigns,
            start_date, end_date,
            platform=platform, account_id=account_id,
            metric=metric, limit=limit,
        )
    elif src == "blend":
        rows = await asyncio.to_thread(
            biz_blend_service.get_top_campaigns,
            start_date, end_date,
            platform=platform, account_id=account_id,
            metric=metric, limit=limit,
        )
    else:
        rows = await asyncio.to_thread(
            biz_daily_report_repository.get_top_campaigns,
            start_date, end_date,
            platform=platform, account_id=account_id,
            metric=metric, limit=limit,
        )
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": rows, "_source": src}


@router.get("/campaign-agg")
async def biz_campaign_aggregated(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    order_by: str = Query("total_spend"),
    order_dir: str = Query("desc"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
    application: ApplicationCtx = Depends(get_current_application),
):
    """Campaign 聚合数据 — 按 campaign_id 分组，时间段内汇总"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    # 阶段 4 X3-filter Round 2：应用级账号白名单守门
    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {
            "code": 0, "message": "ok",
            "data": [], "_source": src, "_hint": flt.hint,
            "_application_id": application.id,
        }
    account_id = flt.account_id

    if src == "attribution":
        rows = await asyncio.to_thread(
            biz_attribution_service.get_campaign_aggregated,
            start_date, end_date,
            platform=platform, account_id=account_id,
            order_by=order_by, order_dir=order_dir,
        )
    elif src == "blend":
        rows = await asyncio.to_thread(
            biz_blend_service.get_campaign_aggregated,
            start_date, end_date,
            platform=platform, account_id=account_id,
            order_by=order_by, order_dir=order_dir,
        )
    else:
        rows = await asyncio.to_thread(
            biz_daily_report_repository.get_campaign_aggregated,
            start_date, end_date,
            platform=platform, account_id=account_id,
            order_by=order_by, order_dir=order_dir,
        )
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": rows, "_source": src}


@router.get("/adgroup-agg")
async def biz_adgroup_aggregated(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None, description="按 campaign 过滤"),
    order_by: str = Query("total_spend"),
    order_dir: str = Query("desc"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """Adgroup 聚合数据 — 按 adgroup_id 分组，支持按 campaign_id 过滤"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)
    if src == "attribution":
        rows = await asyncio.to_thread(
            biz_attribution_service.get_adgroup_aggregated,
            start_date, end_date,
            platform=platform, campaign_id=campaign_id,
            order_by=order_by, order_dir=order_dir,
        )
    elif src == "blend":
        rows = await asyncio.to_thread(
            biz_blend_service.get_adgroup_aggregated,
            start_date, end_date,
            platform=platform, campaign_id=campaign_id,
            order_by=order_by, order_dir=order_dir,
        )
    else:
        rows = await asyncio.to_thread(
            biz_adgroup_daily_repository.get_adgroup_aggregated,
            start_date, end_date,
            platform=platform, campaign_id=campaign_id,
            order_by=order_by, order_dir=order_dir,
        )
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": rows, "_source": src}


@router.get("/ad-agg")
async def biz_ad_aggregated(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    adgroup_id: Optional[str] = Query(None, description="按 adgroup 过滤"),
    order_by: str = Query("total_spend"),
    order_dir: str = Query("desc"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """Ad 聚合数据 — 按 ad_id 分组，支持按 adgroup_id 过滤"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)
    if src == "attribution":
        rows = await asyncio.to_thread(
            biz_attribution_service.get_ad_aggregated,
            start_date, end_date,
            platform=platform,
            campaign_id=campaign_id, adgroup_id=adgroup_id,
            order_by=order_by, order_dir=order_dir,
        )
    elif src == "blend":
        rows = await asyncio.to_thread(
            biz_blend_service.get_ad_aggregated,
            start_date, end_date,
            platform=platform,
            campaign_id=campaign_id, adgroup_id=adgroup_id,
            order_by=order_by, order_dir=order_dir,
        )
    else:
        rows = await asyncio.to_thread(
            biz_ad_daily_repository.get_ad_aggregated,
            start_date, end_date,
            platform=platform, campaign_id=campaign_id, adgroup_id=adgroup_id,
            order_by=order_by, order_dir=order_dir,
        )
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": rows, "_source": src}


@router.get("/adgroup-daily")
async def biz_adgroup_daily(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    name_filter: Optional[str] = Query(None, description="adgroup 名称模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    order_by: str = Query("stat_date"),
    order_dir: str = Query("desc"),
    application: ApplicationCtx = Depends(get_current_application),
):
    _check_dates(start_date, end_date)

    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {
            "code": 0, "message": "ok",
            "data": {"list": [], "total": 0, "page": page, "page_size": page_size,
                     "_hint": flt.hint, "_application_id": application.id},
        }
    account_id = flt.account_id

    data = await asyncio.to_thread(
        biz_adgroup_daily_repository.get_daily_list,
        start_date, end_date,
        platform=platform, account_id=account_id,
        name_filter=name_filter,
        page=page, page_size=page_size,
        order_by=order_by, order_dir=order_dir,
    )
    for row in data["list"]:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": data}


@router.get("/ad-daily")
async def biz_ad_daily_list(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    name_filter: Optional[str] = Query(None, description="ad 名称模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    order_by: str = Query("stat_date"),
    order_dir: str = Query("desc"),
    application: ApplicationCtx = Depends(get_current_application),
):
    _check_dates(start_date, end_date)

    flt = resolve_account_filter(application, account_id)
    if flt.skip_query:
        return {
            "code": 0, "message": "ok",
            "data": {"list": [], "total": 0, "page": page, "page_size": page_size,
                     "_hint": flt.hint, "_application_id": application.id},
        }
    account_id = flt.account_id

    data = await asyncio.to_thread(
        biz_ad_daily_repository.get_daily_list,
        start_date, end_date,
        platform=platform, account_id=account_id,
        name_filter=name_filter,
        page=page, page_size=page_size,
        order_by=order_by, order_dir=order_dir,
    )
    for row in data["list"]:
        for k, v in row.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                row[k] = float(v)
    return {"code": 0, "message": "ok", "data": data}


# ═══════════════════════ 素材分析 ═══════════════════════

@router.get("/creative-analysis")
async def creative_analysis(
    start_date: str = Query(...),
    end_date: str = Query(...),
    platform: Optional[str] = Query(None),
    min_spend: float = Query(10, description="低表现榜最小消耗门槛"),
    top_n: int = Query(5, ge=1, le=20),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """素材分析综合接口 — 基于 ad 维度聚合，返回 overview / top / low / list"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)
    if src == "attribution":
        agg_rows = await asyncio.to_thread(
            biz_attribution_service.get_ad_aggregated,
            start_date, end_date,
            platform=platform,
            order_by="total_spend", order_dir="desc",
        )
    elif src == "blend":
        agg_rows = await asyncio.to_thread(
            biz_blend_service.get_ad_aggregated,
            start_date, end_date,
            platform=platform,
            order_by="total_spend", order_dir="desc",
        )
    else:
        agg_rows = await asyncio.to_thread(
            biz_ad_daily_repository.get_ad_aggregated,
            start_date, end_date,
            platform=platform,
            order_by="total_spend", order_dir="desc",
        )

    def _float(v):
        if v is None:
            return None
        return float(v)

    items = []
    for r in agg_rows:
        items.append({
            "ad_id": r.get("ad_id", ""),
            "ad_name": r.get("ad_name", ""),
            "platform": r.get("platform", ""),
            "impressions": int(r.get("total_impressions") or 0),
            "clicks": int(r.get("total_clicks") or 0),
            "spend": _float(r.get("total_spend")),
            "revenue": _float(r.get("total_revenue")),
            "installs": int(r.get("total_installs") or 0),
            "conversions": int(r.get("total_conversions") or 0),
            "ctr": _float(r.get("ctr")),
            "roas": _float(r.get("roas")),
        })

    total_count = len(items)
    total_spend = sum(i["spend"] or 0 for i in items)
    total_revenue = sum(i["revenue"] or 0 for i in items)
    total_impressions = sum(i["impressions"] for i in items)
    total_clicks = sum(i["clicks"] for i in items)
    avg_ctr = (total_clicks / total_impressions) if total_impressions > 0 else None
    avg_roas = (total_revenue / total_spend) if total_spend > 0 else None

    overview = {
        "total_creatives": total_count,
        "avg_ctr": round(avg_ctr, 6) if avg_ctr is not None else None,
        "avg_completion_rate": None,
        "avg_roas": round(avg_roas, 4) if avg_roas is not None else None,
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
    }

    top_by_roas = sorted(
        [i for i in items if (i["roas"] or 0) > 0],
        key=lambda x: x["roas"] or 0, reverse=True,
    )[:top_n]

    low_performers = sorted(
        [i for i in items if (i["spend"] or 0) >= min_spend],
        key=lambda x: x["roas"] if x["roas"] is not None else 999,
    )[:top_n]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "overview": overview,
            "top": top_by_roas,
            "low": low_performers,
            "list": items,
            "_source": src,
        },
    }
