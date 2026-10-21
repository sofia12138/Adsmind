"""Tenant models and read helpers.

Only ``core.isolation.IsolationMiddleware`` may attach a trusted TenantCtx to a
request.  This module deliberately contains no header/JWT hint middleware.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request
from loguru import logger

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
    """返回成员关系明确授予的租户；查询失败或无成员关系时返回空列表。"""
    try:
        from db import get_app_conn
    except Exception:
        return []
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
        return []

    if not rows:
        return []
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


# ── FastAPI 依赖 ──────────────────────────────────────────

def get_current_tenant(request: Request) -> TenantCtx:
    """FastAPI Depends：从 request.state 取出已注入的租户。

    仅接受服务端鉴权链写入的上下文；缺失时拒绝，禁止静默降级到内部租户。
    """
    tenant = getattr(request.state, "tenant", None)
    if not isinstance(tenant, TenantCtx):
        raise HTTPException(status_code=401, detail="缺少已验证的租户上下文")
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
