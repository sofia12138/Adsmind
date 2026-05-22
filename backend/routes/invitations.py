"""阶段 7 团队邀请路由

API：
  - POST   /api/tenant/invitations              发起邀请（owner/admin）
  - GET    /api/tenant/invitations              列出本租户邀请
  - DELETE /api/tenant/invitations/{id}         撤销邀请
  - GET    /api/auth/invitation/{token}         （无需登录）校验邀请合法性并返回 tenant info
  - POST   /api/auth/invitation/{token}/accept  （可登录或匿名）接受邀请：
       - 已登录：把当前用户加入租户
       - 未登录 + 邮箱已存在：返回 422 提示先登录
       - 未登录 + 邮箱不存在：创建用户 + 加入租户 + 返回 token（自动登录）
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from auth import User, create_token, get_current_user, require_admin
from core.rate_limit import limit as rate_limit
from core.tenant import TenantCtx, get_current_tenant
from repositories import (
    application_repository,
    invitation_repository,
    tenant_member_repository,
    user_repository,
)
from services import email_service, quota_service
from services.user_service import hash_password


def _email_rate_limit():
    from config import get_settings
    try:
        per_hour = int(getattr(get_settings(), "rate_limit_email_per_hour", 30))
    except Exception:
        per_hour = 30
    return rate_limit("email_send", per_hour=max(1, per_hour))


# ── 两个 router：一个挂 /api/tenant，需登录；一个挂 /api/auth，匿名可访问 ──

tenant_router = APIRouter(prefix="/tenant", tags=["团队邀请"])
public_router = APIRouter(prefix="/auth", tags=["团队邀请-接受"])


# ─────────────────────────────────────────────────────────────
# Member 管理（阶段 7 #4）
# ─────────────────────────────────────────────────────────────

class MemberUpdateRoleRequest(BaseModel):
    role: str = Field(description="新角色：owner / admin / member")

    @field_validator("role")
    @classmethod
    def _v_role(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"owner", "admin", "member"}:
            raise ValueError("role 必须是 owner / admin / member")
        return v


def _resolve_user_id(username: str) -> Optional[int]:
    u = user_repository.get_by_username(username)
    return int(u["id"]) if u and u.get("id") else None


def _count_owners(tenant_id: int) -> int:
    rows = tenant_member_repository.list_by_tenant(int(tenant_id))
    return sum(1 for r in rows if (r.get("role") or "").lower() == "owner")


def _serialize_member(row: dict) -> dict:
    """统一成员行：datetime → ISO，附带 user 元信息（在 list_by_tenant 已 join 过）。"""
    out = dict(row)
    v = out.get("joined_at")
    if isinstance(v, datetime):
        out["joined_at"] = v.isoformat(timespec="seconds")
    return out


@tenant_router.get("/members", summary="列出本租户全部成员")
async def list_members(
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    rows = tenant_member_repository.list_by_tenant(int(tenant.id))
    return [_serialize_member(r) for r in rows]


@tenant_router.put("/members/{user_id}", summary="变更成员角色")
async def update_member_role(
    user_id: int,
    req: MemberUpdateRoleRequest,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    current = tenant_member_repository.get(int(tenant.id), int(user_id))
    if not current:
        raise HTTPException(status_code=404, detail="该用户不是本租户成员")

    me_id = _resolve_user_id(admin.username)
    is_self = me_id is not None and int(me_id) == int(user_id)

    # 防止"最后一个 owner"被降级
    if (current.get("role") or "").lower() == "owner" and req.role != "owner":
        if _count_owners(int(tenant.id)) <= 1:
            raise HTTPException(
                status_code=422,
                detail="不能降级最后一个所有者；请先把另一个成员提升为所有者后再操作",
            )

    # 防止自己把自己降到 member 而失去管理权
    if is_self and req.role == "member":
        raise HTTPException(status_code=422,
                            detail="不能把自己降级到普通成员（请由其它管理员操作）")

    updated = tenant_member_repository.update_role(
        int(tenant.id), int(user_id), req.role,
    )
    return _serialize_member(updated) if updated else {"ok": True}


@tenant_router.delete("/members/{user_id}", summary="把成员移出租户")
async def remove_member(
    user_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    current = tenant_member_repository.get(int(tenant.id), int(user_id))
    if not current:
        raise HTTPException(status_code=404, detail="该用户不是本租户成员")

    me_id = _resolve_user_id(admin.username)
    if me_id is not None and int(me_id) == int(user_id):
        raise HTTPException(status_code=422,
                            detail="不能把自己移出租户")

    if (current.get("role") or "").lower() == "owner":
        if _count_owners(int(tenant.id)) <= 1:
            raise HTTPException(
                status_code=422,
                detail="不能移除最后一个所有者；请先把另一个成员提升为所有者后再操作",
            )

    ok = tenant_member_repository.delete(int(tenant.id), int(user_id))
    return {"ok": ok}


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ROLE_ALLOWED = {"owner", "admin", "member"}


# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────

class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member")
    ttl_days: int = Field(default=7, ge=1, le=30)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("role")
    @classmethod
    def _v_role(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _ROLE_ALLOWED:
            raise ValueError(f"role 必须是 {sorted(_ROLE_ALLOWED)} 之一")
        return v


class AcceptInvitationRequest(BaseModel):
    # 未登录用户接受时使用：缺省时若邮箱已注册返回 422
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=64)


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def _build_invitation_url(request: Request, token: str) -> str:
    """构造 invite URL。

    优先级：settings.public_base_url > request.origin > request.host > 相对路径
    """
    base = ""
    try:
        from config import get_settings
        base = (getattr(get_settings(), "public_base_url", "") or "").strip()
    except Exception:
        pass
    if not base:
        base = request.headers.get("origin") or ""
        if not base:
            host = request.headers.get("host") or ""
            if host:
                scheme = request.url.scheme or "http"
                base = f"{scheme}://{host}"
    if base:
        return f"{base.rstrip('/')}/invitation/{token}"
    return f"/invitation/{token}"


def _serialize(row: dict, request: Optional[Request] = None) -> dict:
    """统一序列化：日期 → ISO；附带 invitation_url。"""
    out = dict(row)
    for k in ("expires_at", "accepted_at", "revoked_at", "created_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat(timespec="seconds")
    if request is not None and out.get("token"):
        out["invitation_url"] = _build_invitation_url(request, out["token"])
    return out


# ─────────────────────────────────────────────────────────────
# 1) 已登录侧 API（管理邀请）
# ─────────────────────────────────────────────────────────────

@tenant_router.post("/invitations", summary="发起邀请",
                     dependencies=[Depends(_email_rate_limit())])
async def create_invitation(
    req: InvitationCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    # 防止给自己发邀请
    if req.email == (admin.username or "").lower():
        raise HTTPException(status_code=422, detail="不能给自己发邀请")

    # 防止给已是租户成员的人发
    existing_user = user_repository.get_by_username(req.email)
    if existing_user:
        existing_membership = tenant_member_repository.get(
            tenant_id=int(tenant.id), user_id=int(existing_user["id"]),
        )
        if existing_membership:
            raise HTTPException(
                status_code=422,
                detail=f"用户 {req.email} 已是本租户成员（角色：{existing_membership['role']}）",
            )

    # 防止重复有效邀请
    existing_invite = invitation_repository.find_active_by_tenant_email(
        tenant_id=int(tenant.id), email=req.email,
    )
    if existing_invite:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVITATION_ALREADY_PENDING",
                "message": f"已存在对 {req.email} 的待接受邀请",
                "invitation_id": existing_invite["id"],
            },
        )

    # 配额：发邀请前预检查；pending 邀请算占用
    quota_service.enforce_member_quota(int(tenant.id), count_pending=True, additional=1)

    invited_by = None
    try:
        u = user_repository.get_by_username(admin.username)
        invited_by = int(u["id"]) if u else None
    except Exception:
        pass

    invite = invitation_repository.create(
        tenant_id=int(tenant.id),
        email=req.email,
        role=req.role,
        invited_by_user_id=invited_by,
        ttl_days=req.ttl_days,
    )
    serialized = _serialize(invite, request)

    # 发送邀请邮件（失败不影响主流程，前端仍可复制链接）
    invitation_url = serialized.get("invitation_url") or _build_invitation_url(
        request, invite["token"]
    )
    inviter_name = (
        getattr(admin, "display_name", None)
        or (admin.username or "").split("@", 1)[0]
        or "管理员"
    )
    try:
        sender = email_service.get_sender()
        sent = email_service.send_invitation_email(
            to=req.email,
            tenant_name=tenant.name or f"Tenant#{tenant.id}",
            inviter_display_name=inviter_name,
            role=req.role,
            invitation_url=invitation_url,
            expires_in_days=req.ttl_days,
        )
        serialized["email_delivery"] = sender.kind if sent else "failed"
    except Exception as e:
        logger.warning(f"邀请邮件发送失败：{e}")
        serialized["email_delivery"] = "failed"

    return serialized


@tenant_router.get("/invitations", summary="列出本租户邀请")
async def list_invitations(
    request: Request,
    include_inactive: bool = Query(True),
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    rows = invitation_repository.list_by_tenant(
        int(tenant.id), include_inactive=include_inactive,
    )
    return [_serialize(r, request) for r in rows]


@tenant_router.delete("/invitations/{invite_id}", summary="撤销邀请")
async def revoke_invitation(
    invite_id: int,
    admin: User = Depends(require_admin),
    tenant: TenantCtx = Depends(get_current_tenant),
):
    invite = invitation_repository.get_by_id(invite_id)
    if not invite or int(invite["tenant_id"]) != int(tenant.id):
        raise HTTPException(status_code=404, detail="邀请不存在")
    if invite["status"] != "active":
        raise HTTPException(status_code=422,
                            detail=f"邀请状态={invite['status']}，无法撤销")
    ok = invitation_repository.revoke(invite_id)
    return {"ok": ok}


# ─────────────────────────────────────────────────────────────
# 2) 匿名 / 公共接受流程
# ─────────────────────────────────────────────────────────────

def _resolve_invitation_or_400(token: str) -> dict:
    inv = invitation_repository.get_by_token(token)
    if not inv:
        raise HTTPException(status_code=404, detail="邀请不存在或链接无效")
    if inv["status"] != "active":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVITATION_NOT_ACTIVE",
                "status": inv["status"],
                "message": {
                    "accepted": "该邀请已被接受",
                    "revoked":  "该邀请已被撤销",
                    "expired":  "该邀请已过期，请联系邀请人重新发送",
                }.get(inv["status"], "邀请状态异常"),
            },
        )
    return inv


@public_router.get("/invitation/{token}", summary="预览邀请信息（匿名）")
async def preview_invitation(token: str):
    """匿名调用，前端 /invitation/:token 页加载时调；返回 tenant 名、邀请人、角色等。"""
    inv = invitation_repository.get_by_token(token)
    if not inv:
        raise HTTPException(status_code=404, detail="邀请不存在或链接无效")

    tenant_row = None
    try:
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, slug, plan_id FROM app_tenants WHERE id = %s",
                        (inv["tenant_id"],))
            tenant_row = cur.fetchone()
    except Exception as e:
        logger.warning(f"preview_invitation: 读 tenant 失败 {e}")

    inviter_name = None
    if inv.get("invited_by_user_id"):
        try:
            iu = user_repository.get_by_id(int(inv["invited_by_user_id"]))
            if iu:
                inviter_name = iu.get("display_name") or iu.get("username")
        except Exception:
            pass

    # 检查 email 是否已注册（前端据此切换 UI：登录 vs 注册）
    existing = user_repository.get_by_username(inv["email"])
    email_registered = bool(existing)

    return {
        "status": inv["status"],
        "email": inv["email"],
        "role": inv["role"],
        "tenant_id": inv["tenant_id"],
        "tenant_name": tenant_row["name"] if tenant_row else None,
        "tenant_slug": tenant_row["slug"] if tenant_row else None,
        "inviter_name": inviter_name,
        "expires_at": (
            inv["expires_at"].isoformat(timespec="seconds")
            if isinstance(inv.get("expires_at"), datetime) else inv.get("expires_at")
        ),
        "email_registered": email_registered,
    }


@public_router.post("/invitation/{token}/accept", summary="接受邀请")
async def accept_invitation(
    token: str,
    req: AcceptInvitationRequest,
    request: Request,
):
    inv = _resolve_invitation_or_400(token)
    tenant_id = int(inv["tenant_id"])
    email = inv["email"]
    target_role = inv["role"]

    # 当前是否已登录（从 Authorization header 解析；同步函数，匿名访问时会抛 401 → 转 None）
    current_user: Optional[User] = None
    try:
        current_user = get_current_user(request)
    except Exception:
        current_user = None

    user_row: Optional[dict] = None
    if current_user is not None:
        if (current_user.username or "").lower() != email:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "EMAIL_MISMATCH",
                    "message": (
                        f"当前登录账号是 {current_user.username}，"
                        f"但本邀请发给 {email}。请退出后用受邀邮箱登录或注册。"
                    ),
                },
            )
        user_row = user_repository.get_by_username(current_user.username)
    else:
        existing = user_repository.get_by_username(email)
        if existing:
            # 邮箱已注册但未登录 → 让用户去登录
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LOGIN_REQUIRED",
                    "message": f"邮箱 {email} 已注册账号，请先登录后再接受邀请",
                    "email": email,
                },
            )
        # 全新用户：要求 password
        if not req.password:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "PASSWORD_REQUIRED",
                    "message": "请设置登录密码（≥ 8 位）",
                },
            )
        # 配额二次检查（万一邀请发出后超额了）
        quota_service.enforce_member_quota(tenant_id, count_pending=False, additional=1)

        user_row = user_repository.create(
            username=email,
            password_hash=hash_password(req.password),
            role="admin" if target_role in ("owner", "admin") else "viewer",
            display_name=req.display_name or email.split("@", 1)[0],
            assigned_accounts=[],
        )

    if not user_row:
        raise HTTPException(status_code=500, detail="接受失败：用户记录异常")

    user_id = int(user_row["id"])

    # 真的加入 tenant
    tenant_member_repository.ensure_member(
        tenant_id=tenant_id, user_id=user_id, role=target_role,
    )
    # 如果之前已是 member（用 ensure_member 不会改 role），保持原 role；
    # 这里不强行覆盖，避免 owner 被无意降级。

    # 标记邀请已接受
    invitation_repository.mark_accepted(int(inv["id"]), user_id)

    # 找 tenant 默认应用，返回给前端用作 application context
    default_app = None
    try:
        apps = application_repository.list_by_tenant(tenant_id, include_archived=False)
        default_app = next((a for a in apps if a.get("is_default")), apps[0] if apps else None)
    except Exception:
        pass

    # 找 tenant slug + name
    tenant_slug: Optional[str] = None
    tenant_name: Optional[str] = None
    try:
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT slug, name FROM app_tenants WHERE id = %s",
                        (tenant_id,))
            r = cur.fetchone()
        if r:
            tenant_slug = r.get("slug")
            tenant_name = r.get("name")
    except Exception:
        pass

    # 签发 token：用户接受后自动登录到该租户
    new_token = create_token(
        username=email,
        role=user_row.get("role", "viewer"),
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        application_id=int(default_app["id"]) if default_app else None,
    )

    try:
        from services.panel_service import resolve_allowed_panels
        allowed_panels = resolve_allowed_panels(email, user_row.get("role", "viewer"))
    except Exception:
        allowed_panels = []

    return {
        "ok": True,
        "token": new_token,
        "user": {
            "id": user_id,
            "username": email,
            "role": user_row.get("role"),
            "display_name": user_row.get("display_name"),
        },
        "tenant": {
            "id": tenant_id,
            "slug": tenant_slug,
            "name": tenant_name,
            "tenant_role": target_role,
        },
        "application": (
            {"id": int(default_app["id"]), "name": default_app.get("name"),
             "slug": default_app.get("slug"), "is_default": bool(default_app.get("is_default"))}
            if default_app else None
        ),
        "allowed_panels": allowed_panels,
    }
