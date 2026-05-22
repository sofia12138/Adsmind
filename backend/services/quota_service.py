"""阶段 7 配额限流 MVP — 套餐配额校验 & 用量统计。

设计原则
========
1. **route 层守门**：在 create application / bind account 等"额度敏感"接口前调用
   `enforce_*` 系列函数，超额抛 HTTPException 422。
2. **可绕过白名单**：`internal` tenant 永不计入配额（内部租户跑业务不受 SaaS 套餐限制）。
3. **轻量**：当前只读 app_plans + 现有业务表 count，不引入新的 usage 计数表
   （`app_usage_counters` 是 monthly metric，下一阶段再接入 api_calls）。
4. **友好错误**：HTTPException.detail 是结构体（dict），前端可识别 `code=QUOTA_EXCEEDED`
   并展示"升级套餐"CTA。

错误码约定
==========
- `QUOTA_EXCEEDED_APPLICATIONS`：达到应用数上限
- `QUOTA_EXCEEDED_ACCOUNTS`：达到账号绑定上限
- `QUOTA_EXCEEDED_MEMBERS`：达到团队成员上限（预留，本批未启用）
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from loguru import logger

from core.tenant import INTERNAL_TENANT_ID
from repositories import (
    application_repository,
    biz_account_repository,
    invitation_repository,
    plan_repository,
    tenant_member_repository,
)


def _is_internal(tenant_id: int) -> bool:
    return int(tenant_id) == int(INTERNAL_TENANT_ID)


def _get_tenant_plan_id(tenant_id: int) -> str:
    """读取租户当前 plan_id；查不到默认 free（外部）/ internal（内部）。"""
    try:
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT plan_id FROM app_tenants WHERE id = %s", (tenant_id,))
            row = cur.fetchone()
        if row and row.get("plan_id"):
            return row["plan_id"]
    except Exception as e:
        logger.warning(f"quota_service._get_tenant_plan_id({tenant_id}) 失败：{e}")
    return "internal" if _is_internal(tenant_id) else "free"


# ── 用量统计 ─────────────────────────────────────────────────

def count_applications(tenant_id: int) -> int:
    rows = application_repository.list_by_tenant(int(tenant_id), include_archived=False)
    return len(rows)


def count_accounts(tenant_id: int) -> int:
    """统计该租户已绑定到任意应用的广告账号数（去重 account_id）。"""
    apps = application_repository.list_by_tenant(int(tenant_id), include_archived=False)
    seen: set[str] = set()
    for a in apps:
        bound = biz_account_repository.list_by_application(int(a["id"]))
        for b in bound:
            acc = str(b.get("account_id") or "")
            if acc:
                seen.add(acc)
    return len(seen)


def count_members(tenant_id: int) -> int:
    rows = tenant_member_repository.list_by_tenant(int(tenant_id))
    return len(rows)


def count_pending_invitations(tenant_id: int) -> int:
    """统计 active（待接受）邀请数，用于 members 配额预估。"""
    return invitation_repository.count_active_by_tenant(int(tenant_id))


# ── 视图 ─────────────────────────────────────────────────────

def get_usage(tenant_id: int) -> dict:
    """返回当前租户的"配额视图"：套餐 + 已用 + 上限。前端配额卡片直接消费。"""
    plan_id = _get_tenant_plan_id(int(tenant_id))
    quota = plan_repository.get_quota_for_plan(plan_id)

    apps_used = count_applications(int(tenant_id))
    accounts_used = count_accounts(int(tenant_id))
    members_used = count_members(int(tenant_id))
    pending_invites = count_pending_invitations(int(tenant_id))
    members_effective = members_used + pending_invites  # 含待接受邀请

    return {
        "tenant_id": int(tenant_id),
        "is_internal": _is_internal(tenant_id),
        "plan_id": quota["plan_id"],
        "plan_name": quota["plan_name"],
        "limits": {
            "applications": quota["applications_limit"],
            "accounts": quota["accounts_limit"],
            "members": quota["members_limit"],
            "api_calls_monthly": quota["api_calls_monthly"],
            "ai_calls_monthly": quota["ai_calls_monthly"],
        },
        "usage": {
            "applications": apps_used,
            "accounts": accounts_used,
            "members": members_used,
            "pending_invitations": pending_invites,
        },
        "exhausted": {
            "applications": (not _is_internal(tenant_id)) and apps_used >= quota["applications_limit"],
            "accounts":     (not _is_internal(tenant_id)) and accounts_used >= quota["accounts_limit"],
            "members":      (not _is_internal(tenant_id)) and members_effective >= quota["members_limit"],
        },
    }


# ── 守门 ─────────────────────────────────────────────────────

def _raise_quota_exceeded(code: str, message: str, used: int, limit: int, plan_id: str) -> None:
    """抛 422 + 结构化 detail，前端可统一处理升级 CTA。"""
    raise HTTPException(
        status_code=422,
        detail={
            "code": code,
            "message": message,
            "used": used,
            "limit": limit,
            "plan_id": plan_id,
            "upgrade_hint": "升级到 Starter / Pro 套餐解锁更多额度",
        },
    )


def enforce_application_quota(tenant_id: int) -> None:
    """创建新应用前调用；internal tenant 永不拦截。"""
    if _is_internal(tenant_id):
        return
    plan_id = _get_tenant_plan_id(int(tenant_id))
    limit = plan_repository.get_quota_for_plan(plan_id)["applications_limit"]
    used = count_applications(int(tenant_id))
    if used >= limit:
        _raise_quota_exceeded(
            code="QUOTA_EXCEEDED_APPLICATIONS",
            message=f"当前套餐「{plan_id}」最多可创建 {limit} 个应用（已用 {used}）",
            used=used, limit=limit, plan_id=plan_id,
        )


def enforce_member_quota(tenant_id: int, *, count_pending: bool = True,
                         additional: int = 1) -> None:
    """邀请新成员或将用户加入租户前调用。

    `count_pending=True` 时，pending（active）邀请也算占用 1 个 member 配额，
    避免 owner 在配额内一次性发出 10 个邀请，等接受时全部超额。
    """
    if _is_internal(tenant_id):
        return
    plan_id = _get_tenant_plan_id(int(tenant_id))
    limit = plan_repository.get_quota_for_plan(plan_id)["members_limit"]
    used = count_members(int(tenant_id))
    if count_pending:
        used += count_pending_invitations(int(tenant_id))
    if used + additional > limit:
        _raise_quota_exceeded(
            code="QUOTA_EXCEEDED_MEMBERS",
            message=(
                f"当前套餐「{plan_id}」最多 {limit} 个成员"
                f"（已用 {used}，含待接受的邀请）"
            ),
            used=used, limit=limit, plan_id=plan_id,
        )


def enforce_account_quota(tenant_id: int, *, additional: int = 1,
                          existing_account_id: Optional[str] = None) -> None:
    """绑定 / 新建账号前调用。

    - `additional`：本次操作会新增的"租户级 distinct account_id"数量（通常 1）。
    - `existing_account_id`：若本次操作是"重复绑定一个已属于本租户其它应用的账号"，
      则它不增加 distinct 计数，传入 account_id 后自动放行。
    """
    if _is_internal(tenant_id):
        return
    if existing_account_id:
        apps = application_repository.list_by_tenant(int(tenant_id), include_archived=False)
        for a in apps:
            bound = biz_account_repository.list_by_application(int(a["id"]))
            if any(str(b.get("account_id")) == str(existing_account_id) for b in bound):
                return  # 已是本租户的账号，不增加 distinct count

    plan_id = _get_tenant_plan_id(int(tenant_id))
    limit = plan_repository.get_quota_for_plan(plan_id)["accounts_limit"]
    used = count_accounts(int(tenant_id))
    if used + additional > limit:
        _raise_quota_exceeded(
            code="QUOTA_EXCEEDED_ACCOUNTS",
            message=f"当前套餐「{plan_id}」最多可绑定 {limit} 个广告账号（已用 {used}）",
            used=used, limit=limit, plan_id=plan_id,
        )
