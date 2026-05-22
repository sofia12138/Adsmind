"""阶段 7 #2 付费升级请求数据访问层。

`app_plan_upgrade_requests` 状态机：
  pending → approved   (super_admin 一键批准 + 同步 app_tenants.plan_id)
  pending → rejected   (super_admin 拒绝并填备注)
  pending → canceled   (用户撤回)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from db import get_app_conn
from loguru import logger


def create(*, tenant_id: int, from_plan_id: str, to_plan_id: str,
           contact_email: str, message: Optional[str],
           requested_by_user_id: Optional[int]) -> dict:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_plan_upgrade_requests
               (tenant_id, from_plan_id, to_plan_id, contact_email, message,
                requested_by_user_id, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
            (tenant_id, from_plan_id, to_plan_id, contact_email, message,
             requested_by_user_id),
        )
        req_id = cur.lastrowid
        conn.commit()
    logger.info(
        f"租户 {tenant_id} 申请升级 {from_plan_id} → {to_plan_id} (id={req_id})"
    )
    return get_by_id(req_id)  # type: ignore[return-value]


def get_by_id(req_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.*, t.name AS tenant_name, t.slug AS tenant_slug,
                      u.username AS requested_by_username,
                      u.display_name AS requested_by_display_name
               FROM app_plan_upgrade_requests r
               LEFT JOIN app_tenants t ON t.id = r.tenant_id
               LEFT JOIN app_users u ON u.id = r.requested_by_user_id
               WHERE r.id = %s""",
            (req_id,),
        )
        return cur.fetchone()


def list_by_tenant(tenant_id: int) -> list[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.*, t.name AS tenant_name, t.slug AS tenant_slug
               FROM app_plan_upgrade_requests r
               LEFT JOIN app_tenants t ON t.id = r.tenant_id
               WHERE r.tenant_id = %s
               ORDER BY r.created_at DESC""",
            (tenant_id,),
        )
        return cur.fetchall() or []


def list_all(*, status: Optional[str] = None) -> list[dict]:
    where = ""
    params: tuple = ()
    if status:
        where = "WHERE r.status = %s"
        params = (status,)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT r.*, t.name AS tenant_name, t.slug AS tenant_slug,
                       u.username AS requested_by_username,
                       u.display_name AS requested_by_display_name
                FROM app_plan_upgrade_requests r
                LEFT JOIN app_tenants t ON t.id = r.tenant_id
                LEFT JOIN app_users u ON u.id = r.requested_by_user_id
                {where}
                ORDER BY r.created_at DESC""",
            params,
        )
        return cur.fetchall() or []


def has_pending(tenant_id: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT 1 FROM app_plan_upgrade_requests
               WHERE tenant_id = %s AND status = 'pending' LIMIT 1""",
            (tenant_id,),
        )
        return cur.fetchone() is not None


def approve(req_id: int, *, processed_by_user_id: int,
            admin_note: Optional[str] = None) -> Optional[dict]:
    """批准升级：在事务里改 request.status + tenant.plan_id。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        # 1) 锁定 request 行
        cur.execute(
            """SELECT tenant_id, to_plan_id, status
               FROM app_plan_upgrade_requests
               WHERE id = %s FOR UPDATE""",
            (req_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["status"] != "pending":
            raise ValueError(f"请求状态={row['status']}，仅 pending 可批准")
        tenant_id = row["tenant_id"]
        to_plan = row["to_plan_id"]
        # 2) 更新 tenant.plan_id
        cur.execute(
            "UPDATE app_tenants SET plan_id = %s WHERE id = %s",
            (to_plan, tenant_id),
        )
        # 3) 更新 request 状态
        cur.execute(
            """UPDATE app_plan_upgrade_requests
               SET status = 'approved', processed_at = NOW(),
                   processed_by_user_id = %s, admin_note = %s
               WHERE id = %s""",
            (processed_by_user_id, admin_note, req_id),
        )
        conn.commit()
    logger.info(f"升级请求 {req_id} 已批准；tenant {tenant_id} → {to_plan}")
    return get_by_id(req_id)


def reject(req_id: int, *, processed_by_user_id: int,
           admin_note: Optional[str]) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_plan_upgrade_requests
               SET status = 'rejected', processed_at = NOW(),
                   processed_by_user_id = %s, admin_note = %s
               WHERE id = %s AND status = 'pending'""",
            (processed_by_user_id, admin_note, req_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_by_id(req_id)


def cancel_by_owner(req_id: int, tenant_id: int) -> bool:
    """租户成员撤回自己租户的 pending 请求。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_plan_upgrade_requests
               SET status = 'canceled', processed_at = NOW()
               WHERE id = %s AND tenant_id = %s AND status = 'pending'""",
            (req_id, tenant_id),
        )
        conn.commit()
        return cur.rowcount > 0
