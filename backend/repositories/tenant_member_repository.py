"""租户成员关系数据访问层 —— 封装 `app_tenant_members` 表的 SQL 操作。

阶段 1 用途：
  - 登录时幂等写入 internal tenant 成员关系；
  - 启动时为已有 `app_users` 行批量回填成员关系；
  - 后续阶段 6 多租户切换、邀请、SCIM 等都会扩展此 repo。

详见 docs/saas-transformation.md §20。
"""
from __future__ import annotations

from typing import Optional

from db import get_app_conn
from loguru import logger


# ── 角色映射 ──────────────────────────────────────────────────────
# 全局 user.role → tenant 内默认角色：
#   super_admin / admin  → owner（拥有租户全部权限）
#   其它                 → member
# 阶段 6 启用真正的多租户后，每个租户会有独立的角色字典。
def map_global_role_to_tenant_role(global_role: str) -> str:
    if global_role in ("super_admin", "admin"):
        return "owner"
    return "member"


# ── 单条操作 ──────────────────────────────────────────────────────

def get(tenant_id: int, user_id: int) -> Optional[dict]:
    """读取单条成员关系；不存在时返回 None。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT tenant_id, user_id, role, joined_at
               FROM app_tenant_members
               WHERE tenant_id = %s AND user_id = %s""",
            (tenant_id, user_id),
        )
        return cur.fetchone()


def ensure_member(tenant_id: int, user_id: int, role: str = "member") -> dict:
    """幂等写入：若关系不存在则插入，存在则保留原 role。

    返回最终的成员记录（dict）。`role` 仅在首次写入时生效，已有记录不会被覆盖
    （成员角色变更走 `update_role`）。
    """
    if not tenant_id or not user_id:
        raise ValueError("tenant_id 和 user_id 不能为空")
    with get_app_conn() as conn:
        cur = conn.cursor()
        # INSERT IGNORE 在已存在时返回 rowcount=0；不会修改已有 role
        cur.execute(
            """INSERT IGNORE INTO app_tenant_members (tenant_id, user_id, role)
               VALUES (%s, %s, %s)""",
            (tenant_id, user_id, role),
        )
        conn.commit()
        cur.execute(
            """SELECT tenant_id, user_id, role, joined_at
               FROM app_tenant_members
               WHERE tenant_id = %s AND user_id = %s""",
            (tenant_id, user_id),
        )
        row = cur.fetchone()
    return row or {"tenant_id": tenant_id, "user_id": user_id, "role": role}


def update_role(tenant_id: int, user_id: int, role: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_tenant_members SET role = %s
               WHERE tenant_id = %s AND user_id = %s""",
            (role, tenant_id, user_id),
        )
        conn.commit()
    return get(tenant_id, user_id)


def delete(tenant_id: int, user_id: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM app_tenant_members WHERE tenant_id = %s AND user_id = %s",
            (tenant_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ── 查询 ──────────────────────────────────────────────────────────

def list_by_tenant(tenant_id: int) -> list[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT m.tenant_id, m.user_id, m.role, m.joined_at,
                      u.username, u.display_name, u.role AS global_role
               FROM app_tenant_members m
               INNER JOIN app_users u ON u.id = m.user_id
               WHERE m.tenant_id = %s
               ORDER BY m.joined_at ASC, u.id ASC""",
            (tenant_id,),
        )
        return cur.fetchall() or []


def list_by_user(user_id: int) -> list[dict]:
    """返回用户加入的所有租户（含 tenant 元信息）。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT m.tenant_id, m.role AS tenant_role, m.joined_at,
                      t.slug, t.name, t.plan_id, t.is_internal, t.status, t.enabled_plugins
               FROM app_tenant_members m
               INNER JOIN app_tenants t ON t.id = m.tenant_id
               WHERE m.user_id = %s AND t.status = 'active'
               ORDER BY t.id""",
            (user_id,),
        )
        return cur.fetchall() or []


# ── 批量回填（启动时一次性使用） ─────────────────────────────────

def backfill_internal_members(internal_tenant_id: int = 1) -> int:
    """把所有现有 `app_users` 行幂等地补一条到 internal tenant 的成员关系。

    映射规则：super_admin/admin → owner，其它 → member。
    返回新增写入的行数。
    """
    written = 0
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, role FROM app_users")
            rows = cur.fetchall() or []
            for row in rows:
                user_id = int(row["id"])
                tenant_role = map_global_role_to_tenant_role(row.get("role", ""))
                cur.execute(
                    """INSERT IGNORE INTO app_tenant_members (tenant_id, user_id, role)
                       VALUES (%s, %s, %s)""",
                    (internal_tenant_id, user_id, tenant_role),
                )
                written += cur.rowcount
            conn.commit()
    except Exception as e:
        logger.warning(f"backfill_internal_members 失败：{e}")
        return 0
    if written:
        logger.info(f"已为 {written} 个现有用户补齐 internal tenant 成员关系")
    return written
