"""用户认证模块：JWT + 基于 MySQL 的用户存储（通过 user_service）。

阶段 1 起 JWT payload 增加 `tenant_id` claim；旧 token（无 claim）默认归属
internal tenant (id=1)，向后兼容。详见 docs/saas-transformation.md §7.2。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel

from config import get_settings
from core.tenant import INTERNAL_TENANT_ID
from services import user_service


# ---------- 数据模型（保持与旧版完全兼容）----------
class User(BaseModel):
    username: str
    hashed_password: str
    role: str  # "admin" | "optimizer" | "designer"
    display_name: str = ""
    assigned_accounts: list[str] = []


class UserOut(BaseModel):
    id: Optional[int] = None
    username: str
    role: str
    display_name: str
    assigned_accounts: list[str]
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "optimizer"
    display_name: str = ""
    assigned_accounts: list[str] = []


class UpdateUserRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    display_name: Optional[str] = None
    assigned_accounts: Optional[list[str]] = None


# ---------- 用户操作（委托给 user_service）----------
def get_user(username: str) -> Optional[User]:
    data = user_service.get_user(username)
    if not data:
        return None
    return User(
        username=data["username"],
        hashed_password=data.get("password_hash", ""),
        role=data.get("role", "optimizer"),
        display_name=data.get("display_name", data["username"]),
        assigned_accounts=data.get("assigned_accounts") or [],
    )


def verify_password(plain: str, hashed: str) -> bool:
    return user_service.verify_password(plain, hashed)


def create_user(req: CreateUserRequest) -> User:
    data = user_service.create_user(
        username=req.username,
        password=req.password,
        role=req.role,
        display_name=req.display_name,
        assigned_accounts=req.assigned_accounts,
    )
    return User(
        username=data["username"],
        hashed_password=data.get("password_hash", ""),
        role=data["role"],
        display_name=data.get("display_name", data["username"]),
        assigned_accounts=data.get("assigned_accounts") or [],
    )


def update_user(username: str, req: UpdateUserRequest) -> User:
    data = user_service.update_user(
        username,
        password=req.password,
        role=req.role,
        display_name=req.display_name,
        assigned_accounts=req.assigned_accounts,
    )
    return User(
        username=data["username"],
        hashed_password=data.get("password_hash", ""),
        role=data["role"],
        display_name=data.get("display_name", data["username"]),
        assigned_accounts=data.get("assigned_accounts") or [],
    )


def delete_user(username: str):
    user_service.delete_user(username)


def list_users() -> list[UserOut]:
    rows = user_service.list_users()
    return [UserOut(
        id=u.get("id"),
        username=u["username"],
        role=u.get("role", "optimizer"),
        display_name=u.get("display_name", u["username"]),
        assigned_accounts=u.get("assigned_accounts") or [],
        email=u.get("email"),
    ) for u in rows]


# ---------- JWT ----------
def create_token(
    username: str,
    role: str,
    tenant_id: Optional[int] = None,
    tenant_slug: Optional[str] = None,
    application_id: Optional[int] = None,
) -> str:
    """签发 JWT。

    `tenant_id` / `tenant_slug` 为阶段 1 新增的 claim：
      - 旧调用方传 None → 不写入 claim，向后兼容（解 token 后由 TenantMiddleware
        兜底为 internal tenant id=1）。
      - 新调用方传明确 tenant → 写入 claim，后续中间件直接读取。

    `application_id` 为阶段 4 X1 新增的 claim：
      - None → 不写入；ApplicationMiddleware 自动落到该 tenant 的 default app。
      - 传入 → 写入 claim，中间件直接采用该应用。
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload: dict = {"sub": username, "role": role, "exp": expire}

    # 阶段 1 向后兼容策略：若调用方未指定 tenant，默认归属 internal tenant (id=1)。
    # 这样所有现有 routes/users.py:login 等调用点都自动升级，无需逐处改动。
    if tenant_id is None:
        from core.tenant import INTERNAL_TENANT_ID, INTERNAL_TENANT_SLUG
        tenant_id = INTERNAL_TENANT_ID
        if not tenant_slug:
            tenant_slug = INTERNAL_TENANT_SLUG
    payload["tenant_id"] = int(tenant_id)
    if tenant_slug:
        payload["tenant_slug"] = tenant_slug
    if application_id is not None:
        payload["application_id"] = int(application_id)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")


# ---------- FastAPI 依赖 ----------
def get_current_user(request: Request) -> User:
    verified = getattr(request.state, 'verified_user', None)
    if verified is not None:
        return verified
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:]
    payload = decode_token(token)
    user = get_user(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # 把 JWT 里的 tenant claim 兜底注入 request.state（在 TenantMiddleware 之外提供保险）
    _attach_tenant_from_payload(request, payload)
    return user


def _attach_tenant_from_payload(request: Request, payload: dict) -> None:
    """若 JWT 含 tenant_id 且 request.state 尚未挂载 tenant，则补充挂载。

    这是 TenantMiddleware 的兜底路径：例如某些路由可能跳过中间件，
    或调用链直接使用 Depends(get_current_user) 而未走中间件。
    """
    try:
        existing = getattr(request.state, "tenant", None)
        if existing is not None:
            return
        tid = payload.get("tenant_id")
        if tid is None:
            return
        from core.tenant import get_tenant_by_id  # 延迟引入避免循环依赖

        ctx = get_tenant_by_id(int(tid))
        if ctx is not None:
            request.state.tenant = ctx
    except Exception:
        # 兜底失败不影响鉴权主流程
        pass


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
