"""广告账户管理路由"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth import require_admin, get_current_user
from core.application import ApplicationCtx, get_current_application
from services import account_service
from services.oplog_service import log_operation

router = APIRouter(prefix="/ad-accounts", tags=["广告账户管理"])


def _filter_by_application(application: ApplicationCtx) -> int | None:
    """阶段 4 X3-filter / 阶段 7 多租户加固：账号过滤策略。

    规则表：
      - **internal tenant 的默认应用** → 全量视角（不过滤），兼容内部 26 个账号的历史链路
      - **internal tenant 的非默认应用** → 严格按 application_id 过滤
      - **外部租户（含其默认应用）** → 严格按 application_id 过滤，避免跨租户泄露
    """
    from core.tenant import INTERNAL_TENANT_ID
    if application.is_default and application.tenant_id == INTERNAL_TENANT_ID:
        return None
    return application.id


class AddAccountRequest(BaseModel):
    platform: str
    account_id: str
    account_name: str = ""
    access_token: str
    app_id: str = ""
    app_secret: str = ""
    currency: str = "USD"
    timezone: str = "UTC"


class UpdateAccountRequest(BaseModel):
    account_name: str | None = None
    access_token: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    status: str | None = None


class VerifyTokenRequest(BaseModel):
    platform: str
    access_token: str
    app_id: str = ""
    app_secret: str = ""


@router.get("/")
async def list_accounts(
    platform: str | None = Query(None),
    _user=Depends(get_current_user),
    application: ApplicationCtx = Depends(get_current_application),
):
    app_filter = _filter_by_application(application)
    return {
        "data": account_service.list_accounts(platform, application_id=app_filter),
        "application_id": application.id,
        "application_name": application.name,
        "filtered": app_filter is not None,
    }


@router.get("/{row_id}")
async def get_account(row_id: int, _user=Depends(get_current_user)):
    row = account_service.get_account(row_id)
    if not row:
        return {"error": "not_found"}
    return {"data": row}


@router.post("/verify")
async def verify_token(req: VerifyTokenRequest, _user=Depends(require_admin)):
    result = await account_service.verify_token(
        platform=req.platform,
        access_token=req.access_token,
        app_id=req.app_id,
        app_secret=req.app_secret,
    )
    return result


@router.post("/")
async def add_account(
    req: AddAccountRequest,
    user=Depends(require_admin),
    application: ApplicationCtx = Depends(get_current_application),
):
    # 阶段 4 X3-filter / 阶段 7 加固：新建账号是否要绑定到当前应用
    # - internal tenant + 默认应用 → 保持 NULL，兼容历史"全租户视角"语义
    # - internal tenant + 非默认应用 → 绑定到当前应用
    # - external tenant + 任何应用 → 强制绑定到当前应用（否则刚建完就看不见，
    #   并会绕过配额计数）
    from core.tenant import INTERNAL_TENANT_ID
    is_internal_default = application.is_default and application.tenant_id == INTERNAL_TENANT_ID
    bind_to_app = None if is_internal_default else application.id

    # 阶段 7 配额限流：external 租户检查账号数上限；internal 永不拦截。
    # 这里 existing_account_id 传当次入参的 account_id（若已属于本租户其它应用，
    # quota_service 会自动放行；否则等价于 distinct +1）。
    from services import quota_service
    quota_service.enforce_account_quota(
        application.tenant_id,
        additional=1,
        existing_account_id=req.account_id,
    )

    row = account_service.add_account(
        platform=req.platform,
        account_id=req.account_id,
        account_name=req.account_name,
        access_token=req.access_token,
        app_id=req.app_id,
        app_secret=req.app_secret,
        currency=req.currency,
        timezone=req.timezone,
        application_id=bind_to_app,
    )
    log_operation(
        username=user.username,
        action="添加广告账户",
        target_type="ad_account",
        target_id=req.account_id,
        platform=req.platform,
        after_data=_account_summary(row),
        error_message=f"添加 {req.platform} 账户: {req.account_name or req.account_id} ({req.currency}/{req.timezone})",
    )
    return {"data": row}


@router.put("/{row_id}")
async def update_account(row_id: int, req: UpdateAccountRequest, user=Depends(require_admin)):
    old = account_service.get_account(row_id)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    row = account_service.update_account(row_id, **fields)
    if not row:
        return {"error": "not_found"}
    changed = [k for k in fields if k not in ("access_token", "app_secret")]
    log_operation(
        username=user.username,
        action="更新广告账户",
        target_type="ad_account",
        target_id=str(row_id),
        platform=row.get("platform", ""),
        before_data=_account_summary(old) if old else None,
        after_data=_account_summary(row),
        error_message=f"changed_fields: {', '.join(changed)}" if changed else "更新凭证",
    )
    return {"data": row}


@router.delete("/{row_id}")
async def delete_account(row_id: int, user=Depends(require_admin)):
    existing = account_service.get_account(row_id)
    ok = account_service.delete_account(row_id)
    if not ok:
        return {"error": "not_found"}
    log_operation(
        username=user.username,
        action="删除广告账户",
        target_type="ad_account",
        target_id=str(row_id),
        platform=existing.get("platform", "") if existing else "",
        before_data=_account_summary(existing) if existing else None,
        error_message=f"删除账户: {existing.get('account_name', '') or existing.get('account_id', '')} ({existing.get('platform', '')})" if existing else "",
    )
    return {"ok": True}


@router.post("/{row_id}/default")
async def set_default(row_id: int, user=Depends(require_admin)):
    row = account_service.set_default_account(row_id)
    log_operation(
        username=user.username,
        action="设置默认账户",
        target_type="ad_account",
        target_id=str(row_id),
        platform=row.get("platform", "") if row else "",
        error_message=f"设为默认: {row.get('account_name', '') or row.get('account_id', '')} ({row.get('platform', '')})" if row else "",
    )
    return {"data": row}


def _account_summary(row: dict | None) -> dict | None:
    if not row:
        return None
    skip = {"access_token", "app_secret", "password"}
    return {k: v for k, v in row.items() if k not in skip}
