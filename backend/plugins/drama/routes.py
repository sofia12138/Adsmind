"""剧级分析路由 — /api/drama/*

三个接口：
  GET /api/drama/summary          — 剧级总览（按 content_key 聚合）
  GET /api/drama/locale-breakdown — 语言版本明细（按 language_code 聚合）
  GET /api/drama/trend            — 按天趋势

  POST /api/drama/sync            — 手动触发剧级数据同步

核心约束：
  - keyword 只匹配 localized_drama_name，不匹配 remark_raw
  - 聚合时不能因为 remark 不同把同一部剧拆成多条
  - content_key 是剧级聚合的唯一维度
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from config import get_settings
from plugins.drama import repository as drama_repository
from plugins.drama import sync_job as sync_drama
from plugins.optimizer import sync_job as sync_optimizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drama", tags=["剧级分析"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SOURCE = {"auto", "attribution", "legacy", "blend"}


def _validate_dates(start_date: str, end_date: str) -> None:
    if not _DATE_RE.match(start_date):
        raise HTTPException(400, f"start_date 格式错误，应为 YYYY-MM-DD: {start_date}")
    if not _DATE_RE.match(end_date):
        raise HTTPException(400, f"end_date 格式错误，应为 YYYY-MM-DD: {end_date}")
    if start_date > end_date:
        raise HTTPException(400, f"start_date ({start_date}) 不能晚于 end_date ({end_date})")


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


# ─────────────────────────────────────────────────────────────
# GET /api/drama/summary
# ─────────────────────────────────────────────────────────────

@router.get("/summary", summary="剧级总览（按 content_key 聚合）")
async def drama_summary(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    source_type: Optional[str] = Query(None, description="来源类型: 小程序 / APP"),
    platform: Optional[str] = Query(None, description="媒体平台: tiktok / meta"),
    channel: Optional[str] = Query(None, description="渠道标识"),
    country: Optional[str] = Query(None, description="国家/地区代码"),
    language_code: Optional[str] = Query(None, description="语言代码，如 en / zh / es"),
    keyword: Optional[str] = Query(
        None,
        description="按 localized_drama_name 模糊搜索（不匹配 remark_raw）"
    ),
    optimizer: Optional[str] = Query(
        None,
        description=(
            "按优化师 normalized 名筛选；"
            "传 '未识别' 表示该 campaign 未匹配到任何已知优化师。"
            "数据源为 legacy 时该参数会被忽略并在响应里返回 _warning。"
        ),
    ),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    source: str = Query("auto", description="数据源: auto/attribution/legacy"),
):
    """
    按 content_key 聚合返回剧级总览。

    - keyword 仅匹配 localized_drama_name，remark_raw 不参与搜索
    - 同一部剧不同语言版本会被合并（由 content_key 决定），language_count 字段表示有几个语言版本
    - language_code 参数用于筛选特定语言版本的数据，不影响聚合维度
    """
    _validate_dates(start_date, end_date)
    src = _resolve_source(source)

    if src == "blend":
        result = await asyncio.to_thread(
            drama_repository.query_drama_summary_blend,
            start_date, end_date,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            keyword=keyword,
            language_code=language_code,
            page=page,
            page_size=page_size,
            optimizer=optimizer,
        )
    elif src == "attribution":
        result = await asyncio.to_thread(
            drama_repository.query_drama_summary_attribution,
            start_date, end_date,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            keyword=keyword,
            language_code=language_code,
            page=page,
            page_size=page_size,
            optimizer=optimizer,
        )
    else:
        result = await asyncio.to_thread(
            drama_repository.query_drama_summary,
            start_date, end_date,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            keyword=keyword,
            language_code=language_code,
            page=page,
            page_size=page_size,
        )
        if optimizer:
            result["_warning"] = "legacy 数据源不支持优化师筛选，optimizer 参数已被忽略"
    result["_source"] = src
    return result


# ─────────────────────────────────────────────────────────────
# GET /api/drama/locale-breakdown
# ─────────────────────────────────────────────────────────────

@router.get("/locale-breakdown", summary="语言版本明细（按 language_code 聚合）")
async def locale_breakdown(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    content_key: Optional[str] = Query(None, description="剧内容唯一键（与 drama_id 二选一）"),
    drama_id: Optional[str] = Query(None, description="剧集ID（与 content_key 二选一）"),
    source_type: Optional[str] = Query(None, description="来源类型: 小程序 / APP"),
    platform: Optional[str] = Query(None, description="媒体平台: tiktok / meta"),
    channel: Optional[str] = Query(None, description="渠道标识"),
    country: Optional[str] = Query(None, description="国家/地区代码"),
    optimizer: Optional[str] = Query(
        None,
        description="按优化师 normalized 名筛选；传 '未识别' 表示未匹配。",
    ),
):
    """
    按 language_code 聚合，返回某部剧各语言版本的投放明细。
    content_key 和 drama_id 至少提供一个。
    """
    _validate_dates(start_date, end_date)

    if not content_key and not drama_id:
        raise HTTPException(400, "content_key 或 drama_id 至少提供一个")

    src = _resolve_source("auto")
    if src == "blend":
        rows = await asyncio.to_thread(
            drama_repository.query_locale_breakdown_blend,
            start_date, end_date,
            content_key=content_key,
            drama_id=drama_id,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            optimizer=optimizer,
        )
    elif src == "attribution":
        rows = await asyncio.to_thread(
            drama_repository.query_locale_breakdown_attribution,
            start_date, end_date,
            content_key=content_key,
            drama_id=drama_id,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            optimizer=optimizer,
        )
    else:
        rows = await asyncio.to_thread(
            drama_repository.query_locale_breakdown,
            start_date, end_date,
            content_key=content_key,
            drama_id=drama_id,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
        )
    resp: dict = {"rows": rows, "_source": src}
    if src not in ("blend", "attribution") and optimizer:
        resp["_warning"] = "legacy 数据源不支持优化师筛选，optimizer 参数已被忽略"
    return resp


# ─────────────────────────────────────────────────────────────
# GET /api/drama/trend
# ─────────────────────────────────────────────────────────────

@router.get("/trend", summary="剧级按天趋势")
async def drama_trend(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    content_key: Optional[str] = Query(None, description="剧内容唯一键"),
    language_code: Optional[str] = Query(None, description="语言代码（可选，指定后只看该语言版本）"),
    source_type: Optional[str] = Query(None, description="来源类型: 小程序 / APP"),
    platform: Optional[str] = Query(None, description="媒体平台: tiktok / meta"),
    channel: Optional[str] = Query(None, description="渠道标识"),
    country: Optional[str] = Query(None, description="国家/地区代码"),
    optimizer: Optional[str] = Query(
        None,
        description="按优化师 normalized 名筛选；传 '未识别' 表示未匹配。",
    ),
):
    """
    按天聚合趋势数据。
    可选传入 language_code 查看特定语言版本趋势。
    """
    _validate_dates(start_date, end_date)

    src = _resolve_source("auto")
    if src == "blend":
        rows = await asyncio.to_thread(
            drama_repository.query_drama_trend_blend,
            start_date, end_date,
            content_key=content_key,
            language_code=language_code,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            optimizer=optimizer,
        )
    elif src == "attribution":
        rows = await asyncio.to_thread(
            drama_repository.query_drama_trend_attribution,
            start_date, end_date,
            content_key=content_key,
            language_code=language_code,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
            optimizer=optimizer,
        )
    else:
        rows = await asyncio.to_thread(
            drama_repository.query_drama_trend,
            start_date, end_date,
            content_key=content_key,
            language_code=language_code,
            source_type=source_type,
            platform=platform,
            channel=channel,
            country=country,
        )
    resp: dict = {"rows": rows, "_source": src}
    if src not in ("blend", "attribution") and optimizer:
        resp["_warning"] = "legacy 数据源不支持优化师筛选，optimizer 参数已被忽略"
    return resp


# ─────────────────────────────────────────────────────────────
# POST /api/drama/sync
# ─────────────────────────────────────────────────────────────

@router.post("/sync", summary="手动触发剧级数据同步")
async def trigger_drama_sync(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """
    1. 从 biz_campaign_daily_normalized 扫描数据，解析活动名称 → ad_drama_mapping + fact_drama_daily
    2. 顺带刷新 campaign_optimizer_mapping + fact_optimizer_daily（保证剧集面板优化师下拉新鲜）

    任一步骤失败会单独捕获并在响应里返回，不影响另一步。
    """
    _validate_dates(start_date, end_date)

    drama_result = await asyncio.to_thread(sync_drama.run, start_date, end_date)

    optimizer_result: dict
    try:
        optimizer_result = await asyncio.to_thread(
            sync_optimizer.run, start_date, end_date
        )
    except Exception as exc:  # 不影响剧级同步本身
        logger.exception("sync_optimizer 在剧级同步钩子里失败: %s", exc)
        optimizer_result = {
            "status": "failed",
            "error": str(exc),
        }

    return {
        "status": "ok",
        **drama_result,
        "optimizer_sync": optimizer_result,
    }
