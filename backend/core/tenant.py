"""多租户上下文与中间件（阶段 1 骨架）。

设计原则：
1. 向后兼容：旧 JWT（无 tenant_id claim）默认归属 internal tenant (id=1)。
2. 显式优先：API Key > JWT tenant_id claim > X-Tenant-Id Header > 默认值。
3. 不强制：本阶段中间件只把 tenant 注入 request.state，业务路由可选择性使用；
   后续阶段再逐步把 Depends(get_current_tenant) 落到每个路由上。

详见 docs/saas-transformation.md §7.2、§7.3。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

INTERNAL_TENANT_ID: int = 1
INTERNAL_TENANT_SLUG: str = "internal"


@dataclass
class TenantCtx:
    """请求级租户上下文，挂载在 request.state.tenant。"""

    id: int
    slug: str
    name: str = ""
    plan_id: str = "free"
    status: str = "active"
    is_internal: bool = False
    enabled_plugins: list[str] = field(default_factory=list)

    def has_plugin(self, plugin_key: str) -> bool:
        """判断当前租户是否启用了指定插件。"""
        if self.is_internal:
            return True
        return plugin_key in self.enabled_plugins


_INTERNAL_FALLBACK = TenantCtx(
    id=INTERNAL_TENANT_ID,
    slug=INTERNAL_TENANT_SLUG,
    name="AdsMind 内部",
    plan_id="internal",
    status="active",
    is_internal=True,
    enabled_plugins=[
        "core_ads",
        "drama",
        "optimizer",
        "attribution_metis",
        "returned_conversion",
        "ops_panel_polardb",
        "ai_studio",
    ],
)


# ── 仓库工具 ─────────────────────────────────────────────

def get_tenant_by_id(tenant_id: int) -> Optional[TenantCtx]:
    """从 APP 库读取租户。读不到返回 None（不抛错）。"""
    try:
        from db import get_app_conn
    except Exception as e:
        logger.debug(f"get_tenant_by_id: db 模块不可用：{e}")
        return None

    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, slug, name, plan_id, status, is_internal, enabled_plugins
                   FROM app_tenants WHERE id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"get_tenant_by_id({tenant_id}) 查询失败：{e}")
        return None

    if not row:
        return None
    return _row_to_ctx(row)


def get_tenant_by_slug(slug: str) -> Optional[TenantCtx]:
    try:
        from db import get_app_conn
    except Exception:
        return None
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, slug, name, plan_id, status, is_internal, enabled_plugins
                   FROM app_tenants WHERE slug = %s""",
                (slug,),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"get_tenant_by_slug({slug}) 查询失败：{e}")
        return None
    if not row:
        return None
    return _row_to_ctx(row)


def list_tenants_for_user(user_id: int) -> list[TenantCtx]:
    """返回某个用户可访问的全部租户列表（按 app_tenant_members）。

    若 app_tenant_members 表为空（阶段 1 尚未启用），降级为：
      - super_admin / admin → 返回 internal tenant
      - 其它角色 → 同样返回 internal tenant（向后兼容现有单租户行为）
    """
    try:
        from db import get_app_conn
    except Exception:
        return [_INTERNAL_FALLBACK]
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT t.id, t.slug, t.name, t.plan_id, t.status, t.is_internal, t.enabled_plugins
                   FROM app_tenants t
                   INNER JOIN app_tenant_members m ON m.tenant_id = t.id
                   WHERE m.user_id = %s AND t.status = 'active'
                   ORDER BY t.id""",
                (user_id,),
            )
            rows = cur.fetchall() or []
    except Exception as e:
        logger.warning(f"list_tenants_for_user({user_id}) 查询失败：{e}")
        return [_INTERNAL_FALLBACK]

    if not rows:
        return [_INTERNAL_FALLBACK]
    return [_row_to_ctx(r) for r in rows]


def _row_to_ctx(row: dict) -> TenantCtx:
    enabled_raw = row.get("enabled_plugins")
    if isinstance(enabled_raw, str):
        try:
            enabled = json.loads(enabled_raw) or []
        except Exception:
            enabled = []
    elif isinstance(enabled_raw, list):
        enabled = enabled_raw
    else:
        enabled = []
    return TenantCtx(
        id=int(row["id"]),
        slug=row.get("slug", ""),
        name=row.get("name", ""),
        plan_id=row.get("plan_id", "free"),
        status=row.get("status", "active"),
        is_internal=bool(row.get("is_internal", 0)),
        enabled_plugins=enabled,
    )


# ── 中间件 ────────────────────────────────────────────────

class TenantMiddleware(BaseHTTPMiddleware):
    """从请求中识别租户并注入 request.state.tenant。

    识别优先级（阶段 1 仅 JWT + Header；API Key 在阶段 6 引入）：
      1. JWT.tenant_id claim
      2. X-Tenant-Id header
      3. 默认 internal tenant (id=1)

    本中间件只填充上下文，不阻断请求。鉴权仍由 auth.get_current_user 负责。
    """

    async def dispatch(self, request: Request, call_next):
        tenant_id = _resolve_tenant_id_from_request(request)
        ctx = None
        if tenant_id:
            ctx = get_tenant_by_id(tenant_id)
        if ctx is None:
            ctx = _INTERNAL_FALLBACK
        request.state.tenant = ctx
        return await call_next(request)


def _resolve_tenant_id_from_request(request: Request) -> Optional[int]:
    # 1. JWT
    jwt_tid: Optional[int] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        jwt_tid = _peek_tenant_from_jwt(token)

    # 2. 显式 Header
    header_tid_raw = request.headers.get("X-Tenant-Id")
    header_tid: Optional[int] = None
    if header_tid_raw:
        try:
            header_tid = int(header_tid_raw)
        except ValueError:
            header_tid = None

    # P0 加固：
    #   - JWT 带了 tenant_id：以 JWT 为准；若 header 不一致记 warning 后丢弃
    #   - JWT 没带：允许 header 兜底（兼容旧 token / 后台脚本调用）
    if jwt_tid:
        if header_tid and header_tid != jwt_tid:
            try:
                from loguru import logger as _logger
                _logger.warning(
                    "[security] X-Tenant-Id header={hdr} ≠ JWT tenant_id={jwt}，"
                    "已忽略 header（防越权）",
                    hdr=header_tid, jwt=jwt_tid,
                )
            except Exception:
                pass
        return jwt_tid
    return header_tid


def _peek_tenant_from_jwt(token: str) -> Optional[int]:
    """从 JWT 中无验签地解出 tenant_id（仅用于中间件 hint，鉴权另行处理）。"""
    try:
        from jose import jwt as _jwt
        payload = _jwt.get_unverified_claims(token)
        tid = payload.get("tenant_id")
        if tid is None:
            return None
        return int(tid)
    except Exception:
        return None


# ── FastAPI 依赖 ──────────────────────────────────────────

def get_current_tenant(request: Request) -> TenantCtx:
    """FastAPI Depends：从 request.state 取出已注入的租户。

    若中间件未运行（如脚本调用），降级为 internal tenant。
    """
    tenant = getattr(request.state, "tenant", None)
    if not isinstance(tenant, TenantCtx):
        return _INTERNAL_FALLBACK
    if tenant.status != "active":
        raise HTTPException(status_code=403, detail=f"租户已被{tenant.status}")
    return tenant


def require_plugin(plugin_key: str):
    """FastAPI Depends 工厂：要求当前租户启用指定插件，否则 404。"""

    def _checker(request: Request) -> TenantCtx:
        tenant = get_current_tenant(request)
        if not tenant.has_plugin(plugin_key):
            raise HTTPException(status_code=404, detail="插件未启用")
        return tenant

    return _checker
