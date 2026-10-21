"""Read-only application readiness analytics API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.application import ApplicationCtx, require_application_role
from . import service


router = APIRouter(prefix="/readiness-analytics", tags=["只读就绪度分析"])
read_application = require_application_role("owner", "admin", "editor", "viewer")


@router.get("/overview")
def get_overview(_: ApplicationCtx = Depends(read_application)):
    return service.overview()


@router.get("/details")
def get_details(
    entity_type: service.EntityType | None = None,
    status: str | None = Query(default=None, max_length=64),
    reason_code: str | None = Query(default=None, max_length=128),
    query: str = Query(default="", max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _: ApplicationCtx = Depends(read_application),
):
    return service.details(service.DetailFilters(
        entity_type=entity_type, status=status, reason_code=reason_code,
        query=query, page=page, page_size=page_size,
    ))
