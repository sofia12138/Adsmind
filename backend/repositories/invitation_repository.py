"""租户邀请数据访问层 — 封装 app_tenant_invitations 表的 SQL 操作。

阶段 7 团队邀请流程的存储基座。状态机：
  active  → 待接受（未过期、未撤销、未接受）
  accepted → 已加入（accepted_at IS NOT NULL）
  revoked  → 已撤销（revoked_at IS NOT NULL）
  expired  → 已过期（now > expires_at，且未 accepted/revoked）
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from db import get_app_conn
from loguru import logger


_DEFAULT_TTL_DAYS = 7


def generate_token() -> str:
    """生成 URL-safe 邀请 token；32 字节 = 43 字符 base64url。"""
    return secrets.token_urlsafe(32)


def _row_status(row: dict, now: Optional[datetime] = None) -> str:
    if row.get("accepted_at"):
        return "accepted"
    if row.get("revoked_at"):
        return "revoked"
    exp = row.get("expires_at")
    if exp is not None and now is None:
        now = datetime.now()
    if exp is not None and now is not None and exp < now:
        return "expired"
    return "active"


def _enrich(row: dict) -> dict:
    row["status"] = _row_status(row)
    return row


def create(*, tenant_id: int, email: str, role: str,
           invited_by_user_id: Optional[int],
           ttl_days: int = _DEFAULT_TTL_DAYS) -> dict:
    """生成一条新的邀请；不做配额检查（由 route 层负责）。"""
    token = generate_token()
    expires_at = datetime.now() + timedelta(days=ttl_days)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_tenant_invitations
               (tenant_id, email, role, token, expires_at, invited_by_user_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tenant_id, email, role, token, expires_at, invited_by_user_id),
        )
        invite_id = cur.lastrowid
        conn.commit()
    logger.info(
        f"租户 {tenant_id} 邀请 {email} 加入（role={role} ttl={ttl_days}d id={invite_id}）"
    )
    return get_by_id(invite_id)  # type: ignore[return-value]


def get_by_id(invite_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM app_tenant_invitations WHERE id = %s", (invite_id,))
        row = cur.fetchone()
    return _enrich(row) if row else None


def get_by_token(token: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM app_tenant_invitations WHERE token = %s", (token,))
        row = cur.fetchone()
    return _enrich(row) if row else None


def list_by_tenant(tenant_id: int, *, include_inactive: bool = True) -> list[dict]:
    """列出租户的所有邀请。include_inactive=False 时只返回 active 状态。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT i.*, u.username AS invited_by_username, u.display_name AS invited_by_display_name
               FROM app_tenant_invitations i
               LEFT JOIN app_users u ON u.id = i.invited_by_user_id
               WHERE i.tenant_id = %s
               ORDER BY i.created_at DESC""",
            (tenant_id,),
        )
        rows = cur.fetchall() or []
    enriched = [_enrich(r) for r in rows]
    if include_inactive:
        return enriched
    return [r for r in enriched if r["status"] == "active"]


def revoke(invite_id: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_tenant_invitations
               SET revoked_at = NOW()
               WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL""",
            (invite_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_accepted(invite_id: int, user_id: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_tenant_invitations
               SET accepted_at = NOW(), accepted_user_id = %s
               WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL""",
            (user_id, invite_id),
        )
        conn.commit()
        return cur.rowcount > 0


def count_active_by_tenant(tenant_id: int) -> int:
    """统计 active 邀请数；用于配额预估（待接受邀请算 pending 成员）。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) AS c FROM app_tenant_invitations
               WHERE tenant_id = %s
                 AND accepted_at IS NULL
                 AND revoked_at IS NULL
                 AND expires_at > NOW()""",
            (tenant_id,),
        )
        row = cur.fetchone()
    return int(row["c"]) if row else 0


def find_active_by_tenant_email(tenant_id: int, email: str) -> Optional[dict]:
    """查找某租户给某 email 的"未过期未撤销未接受"邀请。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM app_tenant_invitations
               WHERE tenant_id = %s AND email = %s
                 AND accepted_at IS NULL
                 AND revoked_at IS NULL
                 AND expires_at > NOW()
               LIMIT 1""",
            (tenant_id, email),
        )
        row = cur.fetchone()
    return _enrich(row) if row else None
