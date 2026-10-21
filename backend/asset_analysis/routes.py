"""GET-only material/drama analysis API."""
from __future__ import annotations

import datetime as dt
from fastapi import APIRouter, Depends, Query

from core.application import ApplicationCtx, require_application_role
from .service import AnalysisFilters, Dimension, report


router = APIRouter(prefix="/asset-analysis", tags=["素材与剧目只读分析"])
reader = require_application_role("owner", "admin", "editor", "viewer")


@router.get("/report")
def get_report(
    date_from: dt.date, date_to: dt.date,
    dimension: Dimension = "material",
    platform: str | None = Query(default=None, max_length=32),
    account_id: str | None = Query(default=None, max_length=128),
    coverage_status: str | None = Query(default=None, max_length=40),
    query: str = Query(default="", max_length=255),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
    _: ApplicationCtx = Depends(reader),
):
    return report(AnalysisFilters(date_from=date_from, date_to=date_to, dimension=dimension,
        platform=platform, account_id=account_id, coverage_status=coverage_status,
        query=query, page=page, page_size=page_size))
