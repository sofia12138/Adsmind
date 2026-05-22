"""应用（Application）上下文与中间件（阶段 4 X1）。

设计原则：
1. **二级上下文**：在 TenantCtx 之上叠加 ApplicationCtx，形成 tenant → application 两级。
2. **向后兼容**：若请求未携带 application_id，自动选取该租户的 default application。
3. **显式优先**：JWT.application_id claim > X-Application-Id Header > 该租户的 default application。
4. **不强制**：本阶段中间件只把 application 注入 request.state，业务路由可选择性使用；
   后续 X3 才把 Depends(get_current_application) 落到 /api/biz / ads / reports 等路由上。

详见 docs/saas-transformation.md §22。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

# default application id 与 db.py::_seed_internal_default_application 对齐
DEFAULT_APPLICATION_ID: int = 1


@dataclass
class ApplicationCtx:
    """请求级应用上下文，挂载在 request.state.application。"""

    id: int
    tenant_id: int
    slug: str
    name: str = ""
    platform_type: str = "multi"
    industry: str = ""
    status: str = "active"
    is_default: bool = False
    settings: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == "active"


_INTERNAL_DEFAULT_FALLBACK = ApplicationCtx(
    id=DEFAULT_APPLICATION_ID,
    tenant_id=1,
    slug="default",
    name="AdsMind 默认应用",
    platform_type="multi",
    industry="drama_overseas",
    status="active",
    is_default=True,
    settings={},
)


# ── 仓库工具 ─────────────────────────────────────────────

def get_application_by_id(application_id: int) -> Optional[ApplicationCtx]:
    """从 APP 库读取应用。读不到返回 None。"""
    try:
        from db import get_app_conn
    except Exception as e:
        logger.debug(f"get_application_by_id: db 模块不可用：{e}")
        return None

    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, tenant_id, slug, name, platform_type, industry,
                          status, is_default, settings_json
                   FROM app_applications WHERE id = %s""",
                (application_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"get_application_by_id({application_id}) 查询失败：{e}")
        return None

    if not row:
        return None
    return _row_to_ctx(row)


def get_default_application_for_tenant(tenant_id: int) -> Optional[ApplicationCtx]:
    """返回某租户的 default application（is_default=1 那条）。"""
    try:
        from db import get_app_conn
    except Exception:
        return None
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, tenant_id, slug, name, platform_type, industry,
                          status, is_default, settings_json
                   FROM app_applications
                   WHERE tenant_id = %s AND is_default = 1
                   ORDER BY id ASC LIMIT 1""",
                (tenant_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"get_default_application_for_tenant({tenant_id}) 查询失败：{e}")
        return None
    if not row:
        return None
    return _row_to_ctx(row)


def list_applications_for_tenant(tenant_id: int,
                                 include_archived: bool = False) -> list[ApplicationCtx]:
    """返回某租户下全部应用。"""
    try:
        from db import get_app_conn
    except Exception:
        return []
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            if include_archived:
                cur.execute(
                    """SELECT id, tenant_id, slug, name, platform_type, industry,
                              status, is_default, settings_json
                       FROM app_applications
                       WHERE tenant_id = %s
                       ORDER BY is_default DESC, id ASC""",
                    (tenant_id,),
                )
            else:
                cur.execute(
                    """SELECT id, tenant_id, slug, name, platform_type, industry,
                              status, is_default, settings_json
                       FROM app_applications
                       WHERE tenant_id = %s AND status = 'active'
                       ORDER BY is_default DESC, id ASC""",
                    (tenant_id,),
                )
            rows = cur.fetchall() or []
    except Exception as e:
        logger.warning(f"list_applications_for_tenant({tenant_id}) 查询失败：{e}")
        return []
    return [_row_to_ctx(r) for r in rows]


def _row_to_ctx(row: dict) -> ApplicationCtx:
    raw_settings = row.get("settings_json")
    if isinstance(raw_settings, str):
        try:
            settings_obj = json.loads(raw_settings) or {}
        except Exception:
            settings_obj = {}
    elif isinstance(raw_settings, dict):
        settings_obj = raw_settings
    else:
        settings_obj = {}
    return ApplicationCtx(
        id=int(row["id"]),
        tenant_id=int(row["tenant_id"]),
        slug=row.get("slug", ""),
        name=row.get("name", ""),
        platform_type=row.get("platform_type", "multi"),
        industry=row.get("industry", "") or "",
        status=row.get("status", "active"),
        is_default=bool(row.get("is_default", 0)),
        settings=settings_obj,
    )


# ── 中间件 ────────────────────────────────────────────────

class ApplicationMiddleware(BaseHTTPMiddleware):
    """从请求中识别 application 并注入 request.state.application。

    识别优先级：
      1. JWT.application_id claim
      2. X-Application-Id header
      3. 当前 tenant 的 default application
      4. _INTERNAL_DEFAULT_FALLBACK（最终兜底）

    依赖：TenantMiddleware 必须先运行（顺序由 _setup_middleware 控制）。
    """

    async def dispatch(self, request: Request, call_next):
        application = self._resolve_application(request)
        request.state.application = application
        return await call_next(request)

    def _resolve_application(self, request: Request) -> ApplicationCtx:
        tenant = getattr(request.state, "tenant", None)
        tenant_id = getattr(tenant, "id", None) if tenant else None

        # 1. JWT claim
        app_id_from_jwt = self._peek_application_from_jwt(request)
        if app_id_from_jwt:
            ctx = get_application_by_id(app_id_from_jwt)
            if ctx and (tenant_id is None or ctx.tenant_id == tenant_id):
                return ctx
            # JWT 内 application_id 不属于当前 tenant：忽略并落到 header / default

        # 2. Header
        header_aid = request.headers.get("X-Application-Id")
        if header_aid:
            try:
                ctx = get_application_by_id(int(header_aid))
                if ctx and (tenant_id is None or ctx.tenant_id == tenant_id):
                    return ctx
                # P0 安全加固：header 明确指定了一个非本租户的 application_id → 视为越权
                if ctx and tenant_id is not None and ctx.tenant_id != tenant_id:
                    logger.warning(
                        f"[security] tenant={tenant_id} 尝试访问 application={ctx.id} "
                        f"(实际归属 tenant={ctx.tenant_id})，已拒绝并降级到 default"
                    )
                    # 不抛 403，避免破坏中间件链路的非 API 请求；
                    # 路由层用 get_current_application 时会拿到 default，业务无法越权
            except ValueError:
                pass

        # 3. 该租户 default application
        if tenant_id is not None:
            ctx = get_default_application_for_tenant(tenant_id)
            if ctx:
                return ctx

        # 4. 兜底
        return _INTERNAL_DEFAULT_FALLBACK

    @staticmethod
    def _peek_application_from_jwt(request: Request) -> Optional[int]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        try:
            from jose import jwt as _jwt
            payload = _jwt.get_unverified_claims(token)
            aid = payload.get("application_id")
            if aid is None:
                return None
            return int(aid)
        except Exception:
            return None


# ── FastAPI 依赖 ──────────────────────────────────────────

def get_current_application(request: Request) -> ApplicationCtx:
    """FastAPI Depends：从 request.state 取出已注入的 application。

    若中间件未运行（脚本调用），降级为 internal default。
    若 application 状态非 active，抛 403。
    """
    application = getattr(request.state, "application", None)
    if not isinstance(application, ApplicationCtx):
        return _INTERNAL_DEFAULT_FALLBACK
    if not application.is_active:
        raise HTTPException(status_code=403, detail=f"应用已被{application.status}")
    return application


def require_application_role(*allowed_roles: str):
    """FastAPI Depends 工厂：要求当前用户在 application 内拥有指定角色之一。

    实装逻辑（X5）：
      1. 解析 JWT 拿到用户的全局 role（super_admin / admin / ...）；
      2. 全局 super_admin / admin 自动通过（向后兼容现有 require_admin 用法）；
      3. 其它用户：查 app_application_members 表，role 必须在 allowed_roles 内；
      4. 缺失/状态异常 → 403。

    用法示例（在 routes 中）::

        @router.post("/...", ...)
        async def some_write(
            application: ApplicationCtx = Depends(require_application_role("owner", "admin")),
        ): ...
    """
    valid = {"owner", "admin", "editor", "viewer"}
    allowed = set(allowed_roles) or valid

    def _checker(request: Request) -> ApplicationCtx:
        application = get_current_application(request)

        # 全局 admin 自动通过
        global_role = _peek_global_role_from_jwt(request)
        if global_role in ("super_admin", "admin"):
            return application

        # 否则查应用成员表
        username = _peek_username_from_jwt(request)
        if not username:
            raise HTTPException(status_code=401, detail="需要登录")
        user_id = _user_id_by_username(username)
        if not user_id:
            raise HTTPException(status_code=403, detail="用户不存在")
        try:
            from repositories import application_repository
            member_role = application_repository.get_member_role(application.id, user_id)
        except Exception:
            member_role = None
        if member_role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"需要应用内角色：{', '.join(sorted(allowed))}",
            )
        return application

    return _checker


def _peek_global_role_from_jwt(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        from jose import jwt as _jwt
        payload = _jwt.get_unverified_claims(auth_header[7:])
        return payload.get("role")
    except Exception:
        return None


def _peek_username_from_jwt(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        from jose import jwt as _jwt
        payload = _jwt.get_unverified_claims(auth_header[7:])
        return payload.get("sub")
    except Exception:
        return None


def _user_id_by_username(username: str) -> Optional[int]:
    try:
        from repositories import user_repository
        row = user_repository.get_by_username(username)
        return int(row["id"]) if row and row.get("id") else None
    except Exception:
        return None
