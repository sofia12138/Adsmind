"""用户认证 & 管理路由"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from auth import (
    LoginRequest, CreateUserRequest, UpdateUserRequest, UserOut,
    User, get_user, verify_password, create_token,
    create_user, update_user, delete_user, list_users,
    get_current_user, require_admin,
)
from core.rate_limit import limit as rate_limit
from services.oplog_service import log_operation

router = APIRouter(prefix="/users", tags=["用户管理"])


def _login_rate_limit():
    """单 IP 登录限流：防暴力破解。"""
    from config import get_settings
    try:
        per_min = int(getattr(get_settings(), "rate_limit_login_per_minute", 10))
    except Exception:
        per_min = 10
    return rate_limit("login", per_minute=max(1, per_min))


@router.post("/login", dependencies=[Depends(_login_rate_limit())])
async def login(req: LoginRequest):
    user = get_user(req.username)
    if not user or not verify_password(req.password, user.hashed_password):
        return {"ok": False, "message": "用户名或密码错误"}

    # 阶段 7：按 app_tenant_members 选择用户实际归属的租户。
    # 优先级：
    #   1) 用户加入的"非 internal"租户（多个时取最早加入的，确保外部 SaaS 客户登录后看到自己的租户）
    #   2) 用户加入的 internal 租户（兼容内部员工 + super_admin）
    #   3) 都没有 → 兜底到 internal tenant（向后兼容首次登录的旧账号）
    from core.tenant import INTERNAL_TENANT_ID, INTERNAL_TENANT_SLUG, get_tenant_by_id
    from repositories import tenant_member_repository, user_repository
    tenant_role_default = tenant_member_repository.map_global_role_to_tenant_role(user.role)
    tenant_id = INTERNAL_TENANT_ID
    tenant_slug = INTERNAL_TENANT_SLUG
    tenant_role = tenant_role_default
    user_row = None
    try:
        user_row = user_repository.get_by_username(user.username)
        if user_row and user_row.get("id"):
            user_id = int(user_row["id"])
            memberships = tenant_member_repository.list_by_user(user_id)
            preferred = next((m for m in memberships if not m.get("is_internal")), None)
            internal = next((m for m in memberships if m.get("is_internal")), None)
            chosen = preferred or internal
            if chosen:
                tenant_id = int(chosen["tenant_id"])
                tenant_slug = chosen.get("slug") or tenant_slug
                tenant_role = chosen.get("tenant_role") or tenant_role_default
            else:
                # 旧账号尚未在 app_tenant_members 里：幂等补一条到 internal tenant
                tenant_member_repository.ensure_member(
                    tenant_id=INTERNAL_TENANT_ID,
                    user_id=user_id,
                    role=tenant_role_default,
                )
                tenant_role = tenant_role_default
    except Exception:
        # 成员关系查询/写入失败不阻断登录（向后兼容旧表结构尚未建立的场景）
        pass

    tenant_ctx = get_tenant_by_id(tenant_id)

    token = create_token(user.username, user.role, tenant_id=tenant_id, tenant_slug=tenant_slug)
    from services.panel_service import resolve_allowed_panels
    allowed_panels = resolve_allowed_panels(user.username, user.role)
    return {
        "ok": True,
        "token": token,
        "user": {
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "assigned_accounts": user.assigned_accounts,
        },
        "allowed_panels": allowed_panels,
        "tenant": {
            "id": tenant_id,
            "slug": tenant_slug,
            "name": tenant_ctx.name if tenant_ctx else "AdsMind 内部",
            "plan_id": tenant_ctx.plan_id if tenant_ctx else "internal",
            "is_internal": tenant_ctx.is_internal if tenant_ctx else True,
            "enabled_plugins": tenant_ctx.enabled_plugins if tenant_ctx else [],
            "tenant_role": tenant_role,  # 该用户在当前 tenant 的角色
        },
    }


@router.get("/me")
async def me(request: Request, user: User = Depends(get_current_user)):
    tenant = getattr(request.state, "tenant", None)
    payload = {
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "assigned_accounts": user.assigned_accounts,
    }
    if tenant is not None:
        # 读取该用户在该 tenant 的角色（成员表里可能不存在，则用默认映射兜底）
        from repositories import tenant_member_repository, user_repository
        tenant_role = tenant_member_repository.map_global_role_to_tenant_role(user.role)
        try:
            user_row = user_repository.get_by_username(user.username)
            if user_row and user_row.get("id"):
                member = tenant_member_repository.get(tenant.id, int(user_row["id"]))
                if member and member.get("role"):
                    tenant_role = member["role"]
        except Exception:
            pass
        payload["tenant"] = {
            "id": tenant.id,
            "slug": tenant.slug,
            "name": tenant.name,
            "plan_id": tenant.plan_id,
            "is_internal": tenant.is_internal,
            "enabled_plugins": tenant.enabled_plugins,
            "tenant_role": tenant_role,
        }
    # 阶段 7 #3：邮箱验证状态
    # - email_verified_at 有值 → 已验证
    # - 无值但有未过期的 register verification → 未验证（新注册用户）
    # - 无值且无 pending verification → 历史用户豁免，视为已验证
    try:
        from repositories import user_repository, email_verification_repository
        row = user_repository.get_by_username(user.username)
        if row:
            if row.get("email_verified_at"):
                payload["email_verified"] = True
            elif row.get("id"):
                pending = email_verification_repository.get_active_by_user(
                    int(row["id"]), "register",
                )
                payload["email_verified"] = pending is None
            else:
                payload["email_verified"] = True
    except Exception:
        payload["email_verified"] = True
    return payload


@router.get("/", response_model=list[UserOut])
async def get_users(_: User = Depends(require_admin)):
    return list_users()


@router.post("/", response_model=UserOut)
async def add_user(req: CreateUserRequest, request: Request,
                   admin: User = Depends(require_admin)):
    u = create_user(req)
    # 新用户默认加入当前 admin 所在的 tenant（阶段 1 即 internal）
    try:
        from core.tenant import INTERNAL_TENANT_ID
        from repositories import tenant_member_repository, user_repository
        tenant = getattr(request.state, "tenant", None)
        tenant_id = tenant.id if tenant else INTERNAL_TENANT_ID
        new_row = user_repository.get_by_username(u.username)
        if new_row and new_row.get("id"):
            tenant_member_repository.ensure_member(
                tenant_id=tenant_id,
                user_id=int(new_row["id"]),
                role=tenant_member_repository.map_global_role_to_tenant_role(u.role),
            )
    except Exception:
        pass
    log_operation(
        username=admin.username,
        action="创建用户",
        target_type="user",
        target_id=u.username,
    )
    return UserOut(
        username=u.username, role=u.role,
        display_name=u.display_name, assigned_accounts=u.assigned_accounts,
    )


@router.put("/{username}", response_model=UserOut)
async def edit_user(username: str, req: UpdateUserRequest, admin: User = Depends(require_admin)):
    u = update_user(username, req)
    log_operation(
        username=admin.username,
        action="更新用户",
        target_type="user",
        target_id=username,
    )
    return UserOut(
        username=u.username, role=u.role,
        display_name=u.display_name, assigned_accounts=u.assigned_accounts,
    )


@router.delete("/{username}")
async def remove_user(username: str, admin: User = Depends(require_admin)):
    delete_user(username)
    log_operation(
        username=admin.username,
        action="删除用户",
        target_type="user",
        target_id=username,
    )
    return {"ok": True}
