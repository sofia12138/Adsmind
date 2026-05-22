"""阶段 7 配额查询路由 — `/api/quota/me`

前端配额卡片消费这个接口，渲染套餐 + 已用 / 上限。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import get_current_user
from core.tenant import TenantCtx, get_current_tenant
from services import quota_service

router = APIRouter(prefix="/quota", tags=["配额"])


@router.get("/me", summary="查看当前租户的套餐与用量")
async def my_quota(
    _user=Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    return quota_service.get_usage(tenant.id)
