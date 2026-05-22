"""阶段 7 #2 付费升级请求路由。

设计：
  - 租户成员（admin 角色以上）→ POST /api/billing/upgrade-request 提交申请；
  - super_admin → GET /api/billing/admin/upgrade-requests 看所有 pending；
  - super_admin → POST .../{id}/approve | reject；
  - 不接 Stripe，approve 时直接改 app_tenants.plan_id（事务 + 一致性）。

阶段 8 接支付时可在 approve 链路前加 webhook 校验。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from auth import User, get_current_user, require_admin
from core.tenant import TenantCtx, get_current_tenant
from repositories import billing_repository, plan_repository, user_repository


router = APIRouter(prefix="/billing", tags=["计费"])

_ALLOWED_PLANS = {"free", "starter", "pro", "business", "enterprise"}


def _serialize(row: dict) -> dict:
    out = dict(row)
    for k in ("created_at", "processed_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat(timespec="seconds")
    return out


def _user_id_of(user: User) -> Optional[int]:
    u = user_repository.get_by_username(user.username)
    return int(u["id"]) if u and u.get("id") else None


def _require_platform_admin(
    user: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
) -> User:
    """平台侧审批：须为 internal 租户上的 admin / super_admin（SaaS 租户的 admin 角色不可访问）。"""
    if not tenant.is_internal:
        raise HTTPException(status_code=403, detail="仅平台管理员可访问")
    if (user.role or "").lower() not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="仅平台管理员可访问")
    return user


# ─────────────────────────────────────────────────────────────
# 租户侧
# ─────────────────────────────────────────────────────────────

class UpgradeRequestCreate(BaseModel):
    to_plan_id: str = Field(description="目标套餐 id")
    contact_email: str = Field(min_length=3, max_length=255)
    message: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("to_plan_id")
    @classmethod
    def _v_plan(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _ALLOWED_PLANS:
            raise ValueError(f"to_plan_id 必须是 {sorted(_ALLOWED_PLANS)} 之一")
        return v


@router.post("/upgrade-request", summary="申请升级套餐")
async def create_upgrade_request(
    req: UpgradeRequestCreate,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    if billing_repository.has_pending(int(tenant.id)):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UPGRADE_REQUEST_PENDING",
                "message": "已有未处理的升级申请，请耐心等待平台联系或撤回后再申请",
            },
        )
    plan = plan_repository.get_by_id(req.to_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"套餐 {req.to_plan_id} 不存在")

    current_plan = (tenant.plan_id or "free").lower()
    if current_plan == req.to_plan_id:
        raise HTTPException(status_code=422, detail=f"当前已是「{req.to_plan_id}」套餐")

    row = billing_repository.create(
        tenant_id=int(tenant.id),
        from_plan_id=current_plan,
        to_plan_id=req.to_plan_id,
        contact_email=req.contact_email.strip().lower(),
        message=req.message,
        requested_by_user_id=_user_id_of(admin),
    )
    return _serialize(row)


@router.get("/upgrade-requests", summary="租户自己的升级申请历史")
async def my_upgrade_requests(
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    rows = billing_repository.list_by_tenant(int(tenant.id))
    return [_serialize(r) for r in rows]


@router.post("/upgrade-request/{req_id}/cancel", summary="撤回本租户的 pending 升级申请")
async def cancel_my_upgrade_request(
    req_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    ok = billing_repository.cancel_by_owner(req_id, int(tenant.id))
    if not ok:
        raise HTTPException(status_code=404,
                            detail="申请不存在 / 不在 pending / 非本租户")
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# 平台 super_admin 后台
# ─────────────────────────────────────────────────────────────

class AdminProcessRequest(BaseModel):
    admin_note: Optional[str] = Field(default=None, max_length=2000)


@router.get("/admin/upgrade-requests", summary="[super_admin] 列出全部升级申请")
async def admin_list_requests(
    status: Optional[str] = None,
    _su: User = Depends(_require_platform_admin),
):
    rows = billing_repository.list_all(status=status)
    return [_serialize(r) for r in rows]


@router.post("/admin/upgrade-requests/{req_id}/approve",
             summary="[super_admin] 批准升级")
async def admin_approve(
    req_id: int,
    body: AdminProcessRequest,
    su: User = Depends(_require_platform_admin),
):
    try:
        row = billing_repository.approve(
            req_id,
            processed_by_user_id=_user_id_of(su) or 0,
            admin_note=body.admin_note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail="申请不存在")
    return _serialize(row)


@router.post("/admin/upgrade-requests/{req_id}/reject",
             summary="[super_admin] 驳回升级")
async def admin_reject(
    req_id: int,
    body: AdminProcessRequest,
    su: User = Depends(_require_platform_admin),
):
    row = billing_repository.reject(
        req_id,
        processed_by_user_id=_user_id_of(su) or 0,
        admin_note=body.admin_note,
    )
    if not row:
        raise HTTPException(status_code=404,
                            detail="申请不存在 / 不在 pending")
    return _serialize(row)
