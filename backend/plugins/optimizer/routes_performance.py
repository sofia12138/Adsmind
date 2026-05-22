"""优化师人效报表路由"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from config import get_settings
from plugins.optimizer import repository_performance as optimizer_performance_repository

router = APIRouter(prefix="/optimizer-performance", tags=["优化师人效报表"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SOURCE = {"auto", "attribution", "legacy", "blend"}


def _check_dates(start_date: str, end_date: str):
    if not _DATE_RE.match(start_date):
        raise HTTPException(400, f"start_date 格式错误: {start_date}")
    if not _DATE_RE.match(end_date):
        raise HTTPException(400, f"end_date 格式错误: {end_date}")
    if start_date > end_date:
        raise HTTPException(400, f"start_date({start_date}) > end_date({end_date})")


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
async def optimizer_summary(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    platform: Optional[str] = Query(None, description="平台: tiktok / meta"),
    source_type: Optional[str] = Query(None, description="来源: 小程序 / APP"),
    keyword: Optional[str] = Query(None, description="优化师关键词搜索"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """按优化师维度聚合的人效汇总（含未识别占比）"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    if src == "blend":
        rows = await asyncio.to_thread(
            optimizer_performance_repository.query_optimizer_summary_blend,
            start_date, end_date,
            platform=platform,
            source_type=source_type,
            keyword=keyword,
        )
    elif src == "attribution":
        rows = await asyncio.to_thread(
            optimizer_performance_repository.query_optimizer_summary_attribution,
            start_date, end_date,
            platform=platform,
            source_type=source_type,
            keyword=keyword,
        )
    else:
        rows = await asyncio.to_thread(
            optimizer_performance_repository.query_optimizer_summary,
            start_date, end_date,
            platform=platform,
            source_type=source_type,
            keyword=keyword,
        )

    grand_total_spend = sum(float(r.get("total_spend") or 0) for r in rows)
    unidentified_spend = 0.0

    result = []
    for r in rows:
        total_spend = round(float(r.get("total_spend") or 0), 2)
        active_days = int(r.get("active_days") or 0)
        opt_name = r.get("optimizer_name") or "未识别"

        if opt_name == "未识别":
            unidentified_spend = total_spend

        result.append({
            "optimizer_name":  opt_name,
            "total_spend":     total_spend,
            "spend_share":     round(total_spend / grand_total_spend, 4) if grand_total_spend > 0 else 0,
            "avg_daily_spend": round(total_spend / active_days, 2) if active_days > 0 else 0,
            "active_days":     active_days,
            "campaign_count":  int(r.get("campaign_count") or 0),
            "impressions":     int(r.get("impressions") or 0),
            "clicks":          int(r.get("clicks") or 0),
            "installs":        int(r.get("installs") or 0),
            "registrations":   int(r.get("registrations") or 0),
            "purchase_value":  round(float(r.get("purchase_value") or 0), 2),
            "roas":            _float(r.get("roas")),
        })

    return {
        "code": 0,
        "message": "ok",
        "data": result,
        "_source": src,
        "meta": {
            "grand_total_spend": round(grand_total_spend, 2),
            "unidentified_spend": round(unidentified_spend, 2),
            "unidentified_ratio": round(unidentified_spend / grand_total_spend, 4) if grand_total_spend > 0 else 0,
        },
    }


@router.get("/detail")
async def optimizer_detail(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    optimizer_name: str = Query(..., description="优化师名称"),
    platform: Optional[str] = Query(None, description="平台: tiktok / meta"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """返回指定优化师的 campaign 明细（含匹配来源）"""
    _check_dates(start_date, end_date)
    src = _resolve_source(source)

    if src == "attribution":
        rows = await asyncio.to_thread(
            optimizer_performance_repository.query_optimizer_detail_attribution,
            start_date, end_date, optimizer_name,
            platform=platform,
        )
    else:
        rows = await asyncio.to_thread(
            optimizer_performance_repository.query_optimizer_detail,
            start_date, end_date, optimizer_name,
            platform=platform,
        )

    result = []
    for r in rows:
        result.append({
            "campaign_id":        r.get("campaign_id", ""),
            "campaign_name":      r.get("campaign_name", ""),
            "platform":           r.get("platform", ""),
            "account_id":         r.get("account_id", ""),
            "match_source":       r.get("match_source", "campaign_name"),
            "match_confidence":   _float(r.get("match_confidence")),
            "match_position":     r.get("match_position", ""),
            "spend":              round(float(r.get("spend") or 0), 2),
            "impressions":        int(r.get("impressions") or 0),
            "clicks":             int(r.get("clicks") or 0),
            "installs":           int(r.get("installs") or 0),
            "registrations":      int(r.get("registrations") or 0),
            "purchase_value":     round(float(r.get("purchase_value") or 0), 2),
            "active_days":        int(r.get("active_days") or 0),
            "roas":               _float(r.get("roas")),
        })

    return {"code": 0, "message": "ok", "data": result, "_source": src}


@router.get("/match-distribution")
async def match_distribution(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    platform: Optional[str] = Query(None, description="平台过滤"),
):
    """匹配来源分布统计"""
    _check_dates(start_date, end_date)

    rows = await asyncio.to_thread(
        optimizer_performance_repository.query_match_source_distribution,
        start_date, end_date,
        platform=platform,
    )

    source_labels = {
        "structured_field":   "结构化字段",
        "campaign_name":      "活动名称解析",
        "historical_mapping": "历史映射复用",
        "default_rule":       "默认规则兜底",
        "unassigned":         "未识别",
    }

    result = []
    for r in rows:
        src = r.get("match_source", "campaign_name")
        result.append({
            "match_source":    src,
            "match_source_label": source_labels.get(src, src),
            "campaign_count":  int(r.get("campaign_count") or 0),
            "total_spend":     round(float(r.get("total_spend") or 0), 2),
        })

    return {"code": 0, "message": "ok", "data": result}


@router.post("/sync")
async def optimizer_sync():
    """手动触发优化师数据同步（最近 30 天）"""
    from datetime import date, timedelta
    from plugins.optimizer.sync_job import run as sync_run

    end = date.today()
    start = end - timedelta(days=30)
    result = await asyncio.to_thread(sync_run, str(start), str(end))
    return {"code": 0, "message": "ok", "data": result}


# ---------------------------------------------------------------------------
# 默认规则管理 API
# ---------------------------------------------------------------------------

class DefaultRuleCreate(BaseModel):
    source_type: str = ""
    platform: str = ""
    channel: str = ""
    account_id: str = ""
    country: str = ""
    optimizer_name: str
    priority: int = 0
    is_enabled: int = 1


@router.get("/default-rules")
async def list_default_rules():
    """获取所有默认规则"""
    rows = await asyncio.to_thread(
        optimizer_performance_repository.get_default_rules_all_for_api
    )
    result = []
    for r in rows:
        result.append({
            "id":            r["id"],
            "source_type":   r.get("source_type", ""),
            "platform":      r.get("platform", ""),
            "channel":       r.get("channel", ""),
            "account_id":    r.get("account_id", ""),
            "country":       r.get("country", ""),
            "optimizer_name": r.get("optimizer_name", ""),
            "priority":      r.get("priority", 0),
            "is_enabled":    r.get("is_enabled", 1),
            "created_at":    str(r.get("created_at", "")),
            "updated_at":    str(r.get("updated_at", "")),
        })
    return {"code": 0, "message": "ok", "data": result}


@router.post("/default-rules")
async def create_default_rule(body: DefaultRuleCreate):
    """新增默认规则"""
    if not body.optimizer_name or not body.optimizer_name.strip():
        raise HTTPException(400, "optimizer_name 不能为空")
    cnt = await asyncio.to_thread(
        optimizer_performance_repository.upsert_default_rule,
        body.model_dump(),
    )
    return {"code": 0, "message": "ok", "data": {"affected": cnt}}


@router.delete("/default-rules/{rule_id}")
async def delete_default_rule(rule_id: int):
    """删除默认规则"""
    cnt = await asyncio.to_thread(
        optimizer_performance_repository.delete_default_rule,
        rule_id,
    )
    if cnt == 0:
        raise HTTPException(404, f"规则 {rule_id} 不存在")
    return {"code": 0, "message": "ok", "data": {"deleted": cnt}}
