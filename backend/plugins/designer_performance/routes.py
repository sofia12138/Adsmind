"""设计师人效报表路由"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from config import get_settings
from plugins.designer_performance import repository as designer_performance_repository

router = APIRouter(prefix="/designer-performance", tags=["设计师人效报表"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SOURCE = {"auto", "attribution", "legacy", "blend"}


def _check_dates(start_date: str, end_date: str):
    if not _DATE_RE.match(start_date):
        raise HTTPException(400, f"start_date 格式错误，应为 YYYY-MM-DD，实际: {start_date}")
    if not _DATE_RE.match(end_date):
        raise HTTPException(400, f"end_date 格式错误，应为 YYYY-MM-DD，实际: {end_date}")
    if start_date > end_date:
        raise HTTPException(400, f"start_date({start_date}) 不能大于 end_date({end_date})")


def _resolve_source(source: str) -> str:
    if source not in _ALLOWED_SOURCE:
        raise HTTPException(400, f"source 必须是 {_ALLOWED_SOURCE}, 实际: {source}")
    if source != "auto":
        return source
    settings = get_settings()
    default = (settings.data_source_default or "").lower()
    if default in {"blend", "attribution", "legacy"}:
        return default
    return "attribution" if settings.attribution_primary else "blend"


def _float(v) -> Optional[float]:
    return float(v) if v is not None else None


@router.get("/summary")
async def designer_summary(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    keyword: Optional[str] = Query(None, description="设计师关键词搜索"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """按设计师维度聚合的人效汇总，默认按总消耗降序"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    if src == "blend":
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_summary_blend,
            start_date, end_date,
            platform=platform,
            keyword=keyword,
        )
    elif src == "attribution":
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_summary_attribution,
            start_date, end_date,
            platform=platform,
            keyword=keyword,
        )
    else:
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_summary,
            start_date, end_date,
            platform=platform,
            keyword=keyword,
        )

    result = []
    for r in rows:
        result.append({
            "designer_name":  r.get("designer_name") or "未识别",
            "material_count": int(r.get("material_count") or 0),
            "total_spend":    round(float(r.get("total_spend") or 0), 2),
            "impressions":    int(r.get("impressions") or 0),
            "clicks":         int(r.get("clicks") or 0),
            "installs":       int(r.get("installs") or 0),
            "conversions":    int(r.get("conversions") or 0),
            "purchase_value": round(float(r.get("purchase_value") or 0), 2),
            "ctr":            _float(r.get("ctr")),
            "roas":           _float(r.get("roas")),
        })

    return {"code": 0, "message": "ok", "data": result, "_source": src}


@router.get("/materials")
async def designer_materials(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    designer_name: str = Query(..., description="设计师名称"),
    platform: Optional[str] = Query(None, description="平台过滤: tiktok / meta"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """返回指定设计师在时间范围内的素材明细列表"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    if src == "blend":
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_materials_blend,
            start_date, end_date, designer_name,
            platform=platform,
        )
    elif src == "attribution":
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_materials_attribution,
            start_date, end_date, designer_name,
            platform=platform,
        )
    else:
        rows = await asyncio.to_thread(
            designer_performance_repository.get_designer_materials,
            start_date, end_date, designer_name,
            platform=platform,
        )

    result = []
    for r in rows:
        result.append({
            "ad_id":          r.get("ad_id", ""),
            "ad_name":        r.get("ad_name", ""),
            "platform":       r.get("platform", ""),
            "campaign_name":  r.get("campaign_name", ""),
            "spend":          round(float(r.get("spend") or 0), 2),
            "impressions":    int(r.get("impressions") or 0),
            "clicks":         int(r.get("clicks") or 0),
            "installs":       int(r.get("installs") or 0),
            "registrations":  int(r.get("registrations") or 0),
            "purchase_value": round(float(r.get("purchase_value") or 0), 2),
            "ctr":            _float(r.get("ctr")),
            "roas":           _float(r.get("roas")),
        })

    return {"code": 0, "message": "ok", "data": result, "_source": src}
