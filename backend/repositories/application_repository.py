"""应用（Application）数据访问层 —— 封装 `app_applications` 和
`app_application_members` 表的 SQL 操作。

阶段 4 X1 用途：
  - CRUD 应用（list / get / create / update / archive）
  - 幂等播种租户的 default application
  - 应用成员管理（X5 阶段接入路由）

详见 docs/saas-transformation.md §22。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from db import get_app_conn
from loguru import logger


# ── slug 工具 ─────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """把任意字符串转成 URL-safe slug。"""
    s = (name or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    return s[:60] or "app"


def ensure_unique_slug(tenant_id: int, base_slug: str,
                      exclude_id: Optional[int] = None) -> str:
    """若 tenant 内 slug 已被占用，追加 -2 / -3 直到唯一。"""
    candidate = base_slug
    n = 2
    with get_app_conn() as conn:
        cur = conn.cursor()
        while True:
            if exclude_id is None:
                cur.execute(
                    "SELECT 1 FROM app_applications WHERE tenant_id=%s AND slug=%s LIMIT 1",
                    (tenant_id, candidate),
                )
            else:
                cur.execute(
                    """SELECT 1 FROM app_applications
                       WHERE tenant_id=%s AND slug=%s AND id<>%s LIMIT 1""",
                    (tenant_id, candidate, exclude_id),
                )
            if not cur.fetchone():
                return candidate
            candidate = f"{base_slug}-{n}"
            n += 1


# ── 查询 ──────────────────────────────────────────────────────────

def _row_to_dict(row: dict) -> dict:
    """把 DB 行转成 API 友好的 dict，settings_json 反序列化。"""
    raw = row.get("settings_json")
    if isinstance(raw, str):
        try:
            row["settings"] = json.loads(raw) or {}
        except Exception:
            row["settings"] = {}
    elif isinstance(raw, dict):
        row["settings"] = raw
    else:
        row["settings"] = {}
    row.pop("settings_json", None)
    if isinstance(row.get("is_default"), int):
        row["is_default"] = bool(row["is_default"])
    return row


def get(application_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, tenant_id, slug, name, description, icon_url,
                      platform_type, bundle_id, store_url_ios, store_url_android,
                      industry, status, is_default, settings_json,
                      created_by, created_at, updated_at
               FROM app_applications WHERE id = %s""",
            (application_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_by_tenant(tenant_id: int, include_archived: bool = False) -> list[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        if include_archived:
            cur.execute(
                """SELECT id, tenant_id, slug, name, description, icon_url,
                          platform_type, bundle_id, store_url_ios, store_url_android,
                          industry, status, is_default, settings_json,
                          created_by, created_at, updated_at
                   FROM app_applications
                   WHERE tenant_id = %s
                   ORDER BY is_default DESC, id ASC""",
                (tenant_id,),
            )
        else:
            cur.execute(
                """SELECT id, tenant_id, slug, name, description, icon_url,
                          platform_type, bundle_id, store_url_ios, store_url_android,
                          industry, status, is_default, settings_json,
                          created_by, created_at, updated_at
                   FROM app_applications
                   WHERE tenant_id = %s AND status = 'active'
                   ORDER BY is_default DESC, id ASC""",
                (tenant_id,),
            )
        rows = cur.fetchall() or []
    return [_row_to_dict(r) for r in rows]


# ── 写入 ──────────────────────────────────────────────────────────

def create(tenant_id: int, name: str, *,
           slug: Optional[str] = None,
           description: Optional[str] = None,
           icon_url: Optional[str] = None,
           platform_type: str = "multi",
           bundle_id: Optional[str] = None,
           store_url_ios: Optional[str] = None,
           store_url_android: Optional[str] = None,
           industry: Optional[str] = None,
           settings: Optional[dict] = None,
           is_default: bool = False,
           created_by: Optional[int] = None) -> dict:
    """创建一个应用。slug 缺省时从 name 自动生成，并保证 tenant 内唯一。"""
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    if platform_type not in ("ios", "android", "web", "mini_program", "multi"):
        raise ValueError(f"platform_type 非法: {platform_type}")
    final_slug = ensure_unique_slug(tenant_id, slug or slugify(name))
    settings_str = json.dumps(settings or {}, ensure_ascii=False)

    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_applications
               (tenant_id, slug, name, description, icon_url, platform_type,
                bundle_id, store_url_ios, store_url_android, industry,
                status, is_default, settings_json, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       'active', %s, %s, %s)""",
            (tenant_id, final_slug, name.strip(), description, icon_url,
             platform_type, bundle_id, store_url_ios, store_url_android,
             industry, 1 if is_default else 0, settings_str, created_by),
        )
        new_id = cur.lastrowid
        conn.commit()
    logger.info(f"创建应用 tenant={tenant_id} id={new_id} slug={final_slug}")
    return get(new_id)


def update(application_id: int, **fields) -> Optional[dict]:
    """部分更新一个应用。允许字段：name / description / icon_url / platform_type /
    bundle_id / store_url_ios / store_url_android / industry / settings / slug / status."""
    allowed = {
        "name", "description", "icon_url", "platform_type",
        "bundle_id", "store_url_ios", "store_url_android",
        "industry", "settings", "slug", "status",
    }
    sets: list[str] = []
    params: list = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "settings":
            sets.append("settings_json = %s")
            params.append(json.dumps(v or {}, ensure_ascii=False))
            continue
        if k == "slug" and v:
            current = get(application_id)
            if not current:
                return None
            new_slug = ensure_unique_slug(current["tenant_id"], slugify(v),
                                          exclude_id=application_id)
            sets.append("slug = %s")
            params.append(new_slug)
            continue
        sets.append(f"{k} = %s")
        params.append(v)
    if not sets:
        return get(application_id)
    params.append(application_id)
    sql = f"UPDATE app_applications SET {', '.join(sets)} WHERE id = %s"
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    return get(application_id)


def archive(application_id: int) -> Optional[dict]:
    """软删除：status=archived。is_default 应用不允许 archive（防止租户失去兜底）。"""
    current = get(application_id)
    if not current:
        return None
    if current.get("is_default"):
        raise ValueError("不能归档默认应用")
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE app_applications SET status='archived' WHERE id = %s",
            (application_id,),
        )
        conn.commit()
    return get(application_id)


def restore(application_id: int) -> Optional[dict]:
    """从归档状态恢复为 active。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE app_applications SET status='active' WHERE id = %s",
            (application_id,),
        )
        conn.commit()
    return get(application_id)


# ── 默认应用幂等播种 ──────────────────────────────────────────────

def ensure_default_for_tenant(tenant_id: int,
                              *, name: str = "默认应用",
                              industry: Optional[str] = None) -> dict:
    """幂等：确保 tenant 有一个 is_default=1 的应用；不存在则创建。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id FROM app_applications
               WHERE tenant_id=%s AND is_default=1 LIMIT 1""",
            (tenant_id,),
        )
        row = cur.fetchone()
    if row:
        return get(int(row["id"]))
    return create(tenant_id, name, slug="default",
                  description="租户默认应用，新数据未指定应用时自动归属",
                  industry=industry, is_default=True)


# ── 成员关系（X5 用） ─────────────────────────────────────────────

def add_member(application_id: int, user_id: int, role: str = "editor") -> dict:
    """幂等：加成员到应用。已存在则保留原 role。"""
    if role not in ("owner", "admin", "editor", "viewer"):
        raise ValueError(f"role 非法: {role}")
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT IGNORE INTO app_application_members
               (application_id, user_id, role) VALUES (%s, %s, %s)""",
            (application_id, user_id, role),
        )
        conn.commit()
        cur.execute(
            """SELECT application_id, user_id, role, joined_at
               FROM app_application_members
               WHERE application_id=%s AND user_id=%s""",
            (application_id, user_id),
        )
        return cur.fetchone()


def update_member_role(application_id: int, user_id: int, role: str) -> None:
    if role not in ("owner", "admin", "editor", "viewer"):
        raise ValueError(f"role 非法: {role}")
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_application_members SET role=%s
               WHERE application_id=%s AND user_id=%s""",
            (role, application_id, user_id),
        )
        conn.commit()


def remove_member(application_id: int, user_id: int) -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM app_application_members
               WHERE application_id=%s AND user_id=%s""",
            (application_id, user_id),
        )
        conn.commit()


def list_members(application_id: int) -> list[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT m.application_id, m.user_id, m.role, m.joined_at,
                      u.username, u.email
               FROM app_application_members m
               LEFT JOIN app_users u ON u.id = m.user_id
               WHERE m.application_id = %s
               ORDER BY m.joined_at ASC""",
            (application_id,),
        )
        return cur.fetchall() or []


def get_member_role(application_id: int, user_id: int) -> Optional[str]:
    """读取用户在应用内的角色；不存在返回 None。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT role FROM app_application_members
               WHERE application_id=%s AND user_id=%s""",
            (application_id, user_id),
        )
        row = cur.fetchone()
    return row["role"] if row else None
