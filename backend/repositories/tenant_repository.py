"""租户数据访问层 — 封装 app_tenants 表的写操作。

读操作（get_by_id / get_by_slug / list_tenants_for_user）继续走 `core/tenant.py`，
那里有 ctx 转换 + 缓存兜底逻辑；本 repository 只负责"写"和"slug 唯一性"。

阶段 7 租户自助注册的核心入口。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from db import get_app_conn
from loguru import logger


_SLUG_INVALID = re.compile(r"[^a-z0-9-]+")


def slugify(name: str) -> str:
    """把任意公司名转成 lowercase / hyphen slug。空字符串兜底为 'tenant'。"""
    if not name:
        return "tenant"
    s = name.strip().lower()
    s = _SLUG_INVALID.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:50] or "tenant"


def slug_exists(slug: str) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM app_tenants WHERE slug = %s LIMIT 1", (slug,))
        return cur.fetchone() is not None


def ensure_unique_slug(base_slug: str, max_attempts: int = 100) -> str:
    """在 base_slug 基础上追加 -2 / -3 ... 直到全局唯一。"""
    candidate = base_slug
    for i in range(max_attempts):
        if not slug_exists(candidate):
            return candidate
        candidate = f"{base_slug}-{i + 2}"
    raise RuntimeError(f"无法为 {base_slug} 生成唯一 slug（尝试 {max_attempts} 次）")


def create(*, slug: str, name: str,
           plan_id: str = "free",
           is_internal: bool = False,
           enabled_plugins: Optional[list[str]] = None,
           settings: Optional[dict] = None,
           status: str = "active") -> dict:
    """创建一个新租户并返回完整记录。"""
    enabled_json = json.dumps(enabled_plugins or ["core_ads"], ensure_ascii=False)
    settings_json = json.dumps(settings or {}, ensure_ascii=False)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_tenants
               (slug, name, plan_id, status, is_internal, enabled_plugins, settings)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (slug, name, plan_id, status, 1 if is_internal else 0,
             enabled_json, settings_json),
        )
        tenant_id = cur.lastrowid
        conn.commit()
        cur.execute(
            """SELECT id, slug, name, plan_id, status, is_internal,
                      enabled_plugins, settings, created_at, updated_at
               FROM app_tenants WHERE id = %s""",
            (tenant_id,),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"create tenant 失败：插入后查询不到 id={tenant_id}")
    if isinstance(row.get("enabled_plugins"), str):
        row["enabled_plugins"] = json.loads(row["enabled_plugins"])
    if isinstance(row.get("settings"), str):
        row["settings"] = json.loads(row["settings"])
    logger.info(f"创建租户: id={row['id']} slug={row['slug']} plan={row['plan_id']}")
    return row
