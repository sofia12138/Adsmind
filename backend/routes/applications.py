"""应用（Application）管理路由 — `/api/applications/*`

阶段 4 X1 交付。提供租户内应用的 CRUD、归档/恢复、成员管理。

权限模型（X1 简化版）：
  - 读取（list / get）：tenant 内任何已认证用户均可
  - 写入（create / update / archive / restore）：global super_admin / admin
  - 成员管理：global super_admin / admin（X5 阶段细化为 application 内 owner / admin）

详见 docs/saas-transformation.md §22。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from auth import User, get_current_user, require_admin
from core.tenant import get_current_tenant, TenantCtx
from repositories import application_repository
from services.oplog_service import log_operation

router = APIRouter(prefix="/applications", tags=["应用管理"])


# ── Pydantic Schemas ─────────────────────────────────────────────

class ApplicationOut(BaseModel):
    id: int
    tenant_id: int
    slug: str
    name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    platform_type: str = "multi"
    bundle_id: Optional[str] = None
    store_url_ios: Optional[str] = None
    store_url_android: Optional[str] = None
    industry: Optional[str] = None
    status: str = "active"
    is_default: bool = False
    settings: dict = Field(default_factory=dict)
    created_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _serialize_dt(cls, v):
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, datetime):
            return v.isoformat(timespec="seconds")
        return str(v)


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=512)
    icon_url: Optional[str] = Field(default=None, max_length=512)
    platform_type: str = Field(default="multi",
                                pattern="^(ios|android|web|mini_program|multi)$")
    bundle_id: Optional[str] = Field(default=None, max_length=255)
    store_url_ios: Optional[str] = Field(default=None, max_length=512)
    store_url_android: Optional[str] = Field(default=None, max_length=512)
    industry: Optional[str] = Field(default=None, max_length=64)
    settings: Optional[dict] = None


class ApplicationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    slug: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=512)
    icon_url: Optional[str] = Field(default=None, max_length=512)
    platform_type: Optional[str] = Field(
        default=None, pattern="^(ios|android|web|mini_program|multi)$"
    )
    bundle_id: Optional[str] = Field(default=None, max_length=255)
    store_url_ios: Optional[str] = Field(default=None, max_length=512)
    store_url_android: Optional[str] = Field(default=None, max_length=512)
    industry: Optional[str] = Field(default=None, max_length=64)
    settings: Optional[dict] = None


class MemberIn(BaseModel):
    user_id: int
    role: str = Field(default="editor", pattern="^(owner|admin|editor|viewer)$")


class MemberOut(BaseModel):
    application_id: int
    user_id: int
    role: str
    joined_at: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None

    @field_validator("joined_at", mode="before")
    @classmethod
    def _ser_dt(cls, v):
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, datetime):
            return v.isoformat(timespec="seconds")
        return str(v)


class AdAccountOut(BaseModel):
    id: int
    platform: str
    account_id: str
    account_name: str = ""
    currency: str = "USD"
    timezone: str = "UTC"
    status: str = "ACTIVE"
    is_default: int = 0
    application_id: Optional[int] = None
    last_synced_at: Optional[str] = None

    @field_validator("last_synced_at", mode="before")
    @classmethod
    def _ser_dt(cls, v):
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, datetime):
            return v.isoformat(timespec="seconds")
        return str(v)


class AdAccountBindRequest(BaseModel):
    account_row_id: int


# ── 辅助：把当前 user 转 user_id ──────────────────────────────────

def _user_id_of(user: User) -> Optional[int]:
    from repositories import user_repository
    row = user_repository.get_by_username(user.username)
    return int(row["id"]) if row and row.get("id") else None


def _ensure_same_tenant(application: dict, tenant: TenantCtx) -> None:
    """禁止跨租户访问。"""
    if application["tenant_id"] != tenant.id:
        raise HTTPException(status_code=404, detail="应用不存在")


def _tenant_role(tenant: TenantCtx, user: User) -> tuple[Optional[int], Optional[str]]:
    from repositories import tenant_member_repository
    user_id = _user_id_of(user)
    member = tenant_member_repository.get(tenant.id, user_id) if user_id else None
    return user_id, member.get("role") if member else None


def _ensure_application_visible(application: dict, tenant: TenantCtx, user: User) -> None:
    """Hide same-tenant applications that are not assigned to an ordinary member."""
    _ensure_same_tenant(application, tenant)
    user_id, tenant_role = _tenant_role(tenant, user)
    if tenant_role in ("owner", "admin"):
        return
    if not user_id or application_repository.get_member_role(application["id"], user_id) is None:
        raise HTTPException(status_code=404, detail="应用不存在")


# ── CRUD ─────────────────────────────────────────────────────────

@router.get("", response_model=list[ApplicationOut], summary="列出当前租户的全部应用")
async def list_applications(
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    user_id, tenant_role = _tenant_role(tenant, user)
    if tenant_role not in ("owner", "admin"):
        if not user_id:
            return []
        return application_repository.list_by_tenant_for_user(
            tenant.id, user_id, include_archived=include_archived
        )
    return application_repository.list_by_tenant(tenant.id, include_archived=include_archived)


@router.get("/{application_id}", response_model=ApplicationOut, summary="查看应用详情")
async def get_application(
    application_id: int,
    user: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_application_visible(app, tenant, user)
    return app


@router.post("", response_model=ApplicationOut, summary="创建应用")
async def create_application(
    req: ApplicationCreate,
    request: Request,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    # 阶段 7 配额限流：external 租户按套餐限制应用数；internal 永不拦截
    from services import quota_service
    quota_service.enforce_application_quota(tenant.id)

    try:
        result = application_repository.create(
            tenant_id=tenant.id,
            name=req.name,
            slug=req.slug,
            description=req.description,
            icon_url=req.icon_url,
            platform_type=req.platform_type,
            bundle_id=req.bundle_id,
            store_url_ios=req.store_url_ios,
            store_url_android=req.store_url_android,
            industry=req.industry,
            settings=req.settings,
            created_by=_user_id_of(admin),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_operation(
        username=admin.username,
        action="application.create",
        target_type="application",
        target_id=str(result["id"]),
        after_data={"name": result["name"], "slug": result["slug"]},
    )
    return result


@router.put("/{application_id}", response_model=ApplicationOut, summary="更新应用")
async def update_application(
    application_id: int,
    req: ApplicationUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    before = application_repository.get(application_id)
    if not before:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(before, tenant)

    fields = req.model_dump(exclude_none=True)
    if not fields:
        return before
    try:
        result = application_repository.update(application_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_operation(
        username=admin.username,
        action="application.update",
        target_type="application",
        target_id=str(application_id),
        before_data={k: before.get(k) for k in fields.keys()},
        after_data=fields,
    )
    return result


@router.delete("/{application_id}", summary="归档应用（软删除）")
async def archive_application(
    application_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    before = application_repository.get(application_id)
    if not before:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(before, tenant)
    try:
        application_repository.archive(application_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_operation(
        username=admin.username,
        action="application.archive",
        target_type="application",
        target_id=str(application_id),
    )
    return {"ok": True, "status": "archived"}


@router.post("/{application_id}/restore", summary="从归档恢复应用")
async def restore_application(
    application_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    before = application_repository.get(application_id)
    if not before:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(before, tenant)
    application_repository.restore(application_id)
    log_operation(
        username=admin.username,
        action="application.restore",
        target_type="application",
        target_id=str(application_id),
    )
    return {"ok": True, "status": "active"}


# ── 成员管理（X5 细化）─────────────────────────────────────────────

@router.get("/{application_id}/members", response_model=list[MemberOut],
            summary="列出应用成员")
async def list_application_members(
    application_id: int,
    user: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_application_visible(app, tenant, user)
    return application_repository.list_members(application_id)


@router.post("/{application_id}/members", response_model=MemberOut, summary="添加应用成员")
async def add_application_member(
    application_id: int,
    req: MemberIn,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(app, tenant)
    try:
        from repositories import tenant_member_repository
        if not tenant_member_repository.get(tenant.id, req.user_id):
            raise HTTPException(404, '成员不属于当前租户')
        result = application_repository.add_member(application_id, req.user_id, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_operation(
        username=admin.username,
        action="application.add_member",
        target_type="application",
        target_id=str(application_id),
        after_data={"user_id": req.user_id, "role": req.role},
    )
    return result


@router.put("/{application_id}/members/{user_id}", summary="更新成员角色")
async def update_application_member(
    application_id: int,
    user_id: int,
    req: MemberIn,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(app, tenant)
    try:
        application_repository.update_member_role(application_id, user_id, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_operation(
        username=admin.username,
        action="application.update_member_role",
        target_type="application",
        target_id=str(application_id),
        after_data={"user_id": user_id, "role": req.role},
    )
    return {"ok": True}


@router.delete("/{application_id}/members/{user_id}", summary="移除应用成员")
async def remove_application_member(
    application_id: int,
    user_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(app, tenant)
    application_repository.remove_member(application_id, user_id)
    log_operation(
        username=admin.username,
        action="application.remove_member",
        target_type="application",
        target_id=str(application_id),
        after_data={"user_id": user_id},
    )
    return {"ok": True}


# ── 广告账号绑定（X3）─────────────────────────────────────────────

@router.get("/{application_id}/ad-accounts", response_model=list[AdAccountOut],
            summary="列出绑定到该应用的广告账号")
async def list_application_ad_accounts(
    application_id: int,
    user: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_application_visible(app, tenant, user)
    from repositories import biz_account_repository
    rows = biz_account_repository.list_by_application(application_id)
    return rows


@router.get("/ad-accounts/available", response_model=list[AdAccountOut],
            summary="列出当前租户下可绑定的广告账号（含已绑定其它应用的）")
async def list_available_ad_accounts(
    _: User = Depends(get_current_user),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    from repositories import biz_account_repository
    return biz_account_repository.list_with_application_for_tenant(tenant.id)


@router.post("/{application_id}/ad-accounts/bind", summary="把广告账号绑定到应用")
async def bind_ad_account(
    application_id: int,
    req: AdAccountBindRequest,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(app, tenant)
    from repositories import biz_account_repository

    # 绑定是租户内应用之间的原子转移，不会增加租户账号配额。
    affected = biz_account_repository.transfer_to_application(
        req.account_row_id, application_id
    )
    if affected == 0:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    log_operation(
        username=admin.username,
        action="application.bind_ad_account",
        target_type="application",
        target_id=str(application_id),
        after_data={"account_row_id": req.account_row_id},
    )
    return {"ok": True, "affected": affected}


@router.post("/{application_id}/ad-accounts/unbind", summary="把广告账号从应用解绑")
async def unbind_ad_account(
    application_id: int,
    req: AdAccountBindRequest,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    app = application_repository.get(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    _ensure_same_tenant(app, tenant)
    from repositories import biz_account_repository
    if app.get("is_default"):
        raise HTTPException(status_code=409, detail="默认应用的账号不能解绑")
    default_app = application_repository.ensure_default_for_tenant(tenant.id)
    affected = biz_account_repository.transfer_to_application(
        req.account_row_id,
        int(default_app["id"]),
        from_application_id=application_id,
    )
    if affected == 0:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    log_operation(
        username=admin.username,
        action="application.unbind_ad_account",
        target_type="application",
        target_id=str(application_id),
        before_data={"account_row_id": req.account_row_id},
    )
    return {"ok": True, "affected": affected}
