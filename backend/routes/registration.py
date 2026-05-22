"""阶段 7 租户自助注册路由 — `/api/auth/register`

允许新 SaaS 客户自助完成"注册 → 自动创建租户 + 默认应用 + 管理员账号 → 自动登录"
的完整链路，不需要内部 admin 介入。

幂等性 & 失败回滚：
  - username（=email）唯一性冲突 → 422，事务不开启
  - 创建租户后写用户失败 → 删除新建的 tenant（轻量补偿）
  - 默认应用创建失败 → 不阻断注册（用户登录后由 lifespan 兜底创建）

安全限制（MVP 版本）：
  - 邮箱格式 + 密码长度（≥8）基础校验
  - 未做：邮箱验证码、reCAPTCHA、IP 限流 → 阶段 7 后续补
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from loguru import logger

from auth import create_token
from core.rate_limit import limit as rate_limit
from services import email_service
from services.user_service import hash_password
from repositories import (
    application_repository,
    email_verification_repository,
    tenant_member_repository,
    tenant_repository,
    user_repository,
)

router = APIRouter(prefix="/auth", tags=["租户自助注册"])

_PASSWORD_MIN = 8
_COMPANY_NAME_MAX = 100
# 简化版邮箱校验：满足 user@domain.tld 即可，避免引入 email-validator 依赖
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255,
                       description="联系邮箱，作为登录用户名")
    password: str = Field(min_length=_PASSWORD_MIN,
                          max_length=128,
                          description=f"登录密码，至少 {_PASSWORD_MIN} 位")
    company_name: str = Field(min_length=1, max_length=_COMPANY_NAME_MAX,
                              description="公司 / 团队名称，作为租户名")
    plan_id: Optional[str] = Field(default="free",
                                   pattern="^(free|pro|biz|enterprise)$",
                                   description="套餐：free / pro / biz / enterprise")
    display_name: Optional[str] = Field(default=None, max_length=64,
                                        description="管理员显示名（缺省用邮箱前缀）")

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v


def _build_verify_url(request: Optional[Request], token: str) -> str:
    """构造邮箱验证 URL。

    优先级：settings.public_base_url > request.origin > request.host > 相对路径
    """
    base = ""
    try:
        from config import get_settings
        base = (getattr(get_settings(), "public_base_url", "") or "").strip()
    except Exception:
        pass
    if not base and request is not None:
        base = request.headers.get("origin") or ""
        if not base:
            host = request.headers.get("host") or ""
            if host:
                scheme = request.url.scheme or "http"
                base = f"{scheme}://{host}"
    if base:
        return f"{base.rstrip('/')}/verify-email/{token}"
    return f"/verify-email/{token}"


def _register_rate_limit():
    """注册端点的 per-IP 限流；返回 dependency。"""
    from config import get_settings
    try:
        per_hour = int(getattr(get_settings(), "rate_limit_register_per_hour", 20))
    except Exception:
        per_hour = 20
    return rate_limit("register", per_hour=max(1, per_hour))


def _email_rate_limit():
    """重发验证 / 邀请类邮件操作的 per-IP 限流。"""
    from config import get_settings
    try:
        per_hour = int(getattr(get_settings(), "rate_limit_email_per_hour", 30))
    except Exception:
        per_hour = 30
    return rate_limit("email_send", per_hour=max(1, per_hour))


@router.post("/register", summary="租户自助注册",
             dependencies=[Depends(_register_rate_limit())])
async def register(req: RegisterRequest, request: Request):
    email = req.email  # validator 已规范为 lowercase

    if user_repository.get_by_username(email):
        raise HTTPException(status_code=422,
                            detail=f"邮箱 {email} 已被注册，请直接登录或使用其它邮箱")

    base_slug = tenant_repository.slugify(req.company_name)
    final_slug = tenant_repository.ensure_unique_slug(base_slug)

    tenant_row = tenant_repository.create(
        slug=final_slug,
        name=req.company_name.strip(),
        plan_id=req.plan_id or "free",
        is_internal=False,
        enabled_plugins=["core_ads"],
        status="active",
    )
    tenant_id = int(tenant_row["id"])

    try:
        user_row = user_repository.create(
            username=email,
            password_hash=hash_password(req.password),
            role="admin",
            display_name=(req.display_name or email.split("@", 1)[0]),
            assigned_accounts=[],
        )
        user_id = int(user_row["id"])
    except Exception as e:
        logger.error(f"register: 创建 user 失败，回滚 tenant id={tenant_id}: {e}")
        try:
            from db import get_app_conn
            with get_app_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM app_tenants WHERE id = %s", (tenant_id,))
                conn.commit()
        except Exception:
            logger.warning(f"租户回滚失败（手动清理 id={tenant_id}）")
        raise HTTPException(status_code=500, detail="注册失败：用户创建异常")

    try:
        tenant_member_repository.ensure_member(
            tenant_id=tenant_id,
            user_id=user_id,
            role="owner",  # 注册者是租户 owner
        )
    except Exception as e:
        logger.warning(f"register: tenant_member 写入失败（用户仍可登录）：{e}")

    default_app: Optional[dict] = None
    try:
        default_app = application_repository.ensure_default_for_tenant(
            tenant_id=tenant_id,
            name=f"{req.company_name.strip()} 默认应用",
        )
    except Exception as e:
        logger.warning(f"register: default application 创建失败（首次登录时兜底创建）：{e}")

    application_id = int(default_app["id"]) if default_app else None

    token = create_token(
        username=email,
        role="admin",
        tenant_id=tenant_id,
        tenant_slug=final_slug,
        application_id=application_id,
    )

    # 返回真实 allowed_panels；前端 AuthGuard 据此决定能进哪些页面。
    # 当前所有 SaaS owner 走 role=admin 角色的默认 panels（与内部租户一致）；
    # 菜单的"插件相关项"由前端 hasPlugin(tenant.enabledPlugins) 进一步收窄，
    # 所以新租户即使 admin 也只看到 core_ads 范围内的菜单。
    try:
        from services.panel_service import resolve_allowed_panels
        allowed_panels = resolve_allowed_panels(email, "admin")
    except Exception:
        allowed_panels = []

    # 阶段 7 #3：自动生成邮箱验证 token 并发送验证邮件。
    # 邮件发送失败不影响注册结果；console backend 下 verification_url 仍随响应返回（开发友好）。
    verification_url: Optional[str] = None
    verification_token: Optional[str] = None
    email_delivery = "skipped"  # console | smtp | disabled | failed | skipped
    try:
        v = email_verification_repository.create(
            user_id=user_id, email=email, purpose="register",
        )
        verification_token = v["token"]
        verification_url = _build_verify_url(request, verification_token)
        sender = email_service.get_sender()
        sent = email_service.send_verify_email(
            to=email, verify_url=verification_url, expires_in_hours=48,
        )
        email_delivery = sender.kind if sent else "failed"
    except Exception as e:
        logger.warning(f"register: email verification 创建/发送失败：{e}")
        email_delivery = "failed"

    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user_id,
            "username": email,
            "role": "admin",
            "display_name": user_row.get("display_name"),
            "assigned_accounts": [],
        },
        "tenant": {
            "id": tenant_id,
            "slug": final_slug,
            "name": tenant_row["name"],
            "plan_id": tenant_row["plan_id"],
            "is_internal": False,
            "enabled_plugins": tenant_row.get("enabled_plugins") or ["core_ads"],
            "tenant_role": "owner",
        },
        "application": (
            {
                "id": application_id,
                "slug": default_app.get("slug") if default_app else None,
                "name": default_app.get("name") if default_app else None,
                "is_default": True,
            }
            if default_app
            else None
        ),
        "allowed_panels": allowed_panels,
        "next_step": "bind_ad_account",  # 前端可据此跳转到绑定向导
        "email_verification": {
            "required": False,  # MVP 不强制；后续可改 True 启用强校验
            # console / disabled / failed 时返回链接（开发或回退场景）；
            # smtp 成功送达时不再回传链接，强制走邮件
            "verification_url": (
                verification_url if email_delivery in ("console", "disabled",
                                                       "failed", "skipped")
                else None
            ),
            "delivery": email_delivery,
            "expires_in_hours": 48,
        },
    }


# ─────────────────────────────────────────────────────────────
# 阶段 7 #3 邮箱验证：GET/POST 端点（注册路由组下）
# ─────────────────────────────────────────────────────────────

@router.get("/verify-email/{token}", summary="邮箱验证（GET 兼容浏览器直访）")
async def verify_email_get(token: str):
    return await _do_verify_email(token)


@router.post("/verify-email/{token}", summary="邮箱验证（POST 标准）")
async def verify_email_post(token: str):
    return await _do_verify_email(token)


async def _do_verify_email(token: str):
    rec = email_verification_repository.get_by_token(token)
    if not rec:
        raise HTTPException(status_code=404, detail="验证链接无效")
    if rec.get("verified_at") is not None:
        return {"ok": True, "already_verified": True,
                "email": rec.get("email")}
    exp = rec.get("expires_at")
    from datetime import datetime as _dt
    if exp and isinstance(exp, _dt) and exp < _dt.now():
        raise HTTPException(
            status_code=422,
            detail={"code": "VERIFICATION_EXPIRED",
                    "message": "验证链接已过期，请重新申请"},
        )
    ok = email_verification_repository.mark_verified(int(rec["id"]))
    if ok and rec.get("user_id"):
        user_repository.mark_email_verified(int(rec["user_id"]))
    return {"ok": True, "email": rec.get("email")}


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


@router.post("/resend-verification", summary="重发邮箱验证",
             dependencies=[Depends(_email_rate_limit())])
async def resend_verification(req: ResendVerificationRequest, request: Request):
    email = req.email.strip().lower()
    user = user_repository.get_by_username(email)
    if not user:
        return {"ok": True}
    if user.get("email_verified_at"):
        return {"ok": True, "already_verified": True}
    v = email_verification_repository.create(
        user_id=int(user["id"]), email=email, purpose="register",
    )
    verification_url = _build_verify_url(request, v["token"])
    sender = email_service.get_sender()
    sent = email_service.send_verify_email(
        to=email, verify_url=verification_url, expires_in_hours=48,
    )
    delivery = sender.kind if sent else "failed"
    return {
        "ok": True,
        "delivery": delivery,
        # 仅 console / disabled / failed 时回传链接
        "verification_url": (
            verification_url if delivery in ("console", "disabled", "failed") else None
        ),
        "expires_in_hours": 48,
    }


# 注册端点的简单只读"检查 slug 可用性"，前端表单实时校验用
class CheckSlugRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=_COMPANY_NAME_MAX)


@router.post("/check-availability", summary="校验邮箱 / slug 是否可用")
async def check_availability(email: Optional[str] = None,
                             company_name: Optional[str] = None):
    result: dict = {}
    if email:
        result["email_available"] = user_repository.get_by_username(email.lower()) is None
    if company_name:
        slug = tenant_repository.slugify(company_name)
        result["proposed_slug"] = slug
        result["slug_available"] = not tenant_repository.slug_exists(slug)
    return result
