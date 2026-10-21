"""文案包资产库 — asset_copy_packs 表 CRUD"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import tenant_cursor
from db import get_app_conn


def _row_to_dict(row: dict) -> dict:
    ct = row.get("country_tags")
    tt = row.get("theme_tags")
    if isinstance(ct, str):
        ct = json.loads(ct)
    if isinstance(tt, str):
        tt = json.loads(tt)
    return {
        "id": row["id"],
        "org_id": row.get("org_id", ""),
        "name": row.get("name", ""),
        "primary_text": row.get("primary_text", ""),
        "headline": row.get("headline", ""),
        "description": row.get("description", ""),
        "language": row.get("language", ""),
        "product_name": row.get("product_name", ""),
        "channel": row.get("channel", ""),
        "country_tags": ct or [],
        "theme_tags": tt or [],
        "remark": row.get("remark", ""),
        "status": row.get("status", "active"),
        "usage_count": row.get("usage_count", 0),
        "last_used_at": row["last_used_at"].isoformat() if row.get("last_used_at") else None,
        "created_by": row.get("created_by", ""),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def list_all(*, status: str | None = None, keyword: str | None = None) -> list[dict]:
    where, params = ["1=1"], []
    if status:
        where.append("status = %s")
        params.append(status)
    if keyword:
        kw = f"%{keyword}%"
        where.append("(name LIKE %s OR primary_text LIKE %s OR headline LIKE %s OR product_name LIKE %s)")
        params.extend([kw, kw, kw, kw])
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute(
            f"SELECT * FROM asset_copy_packs WHERE {' AND '.join(where)} ORDER BY id DESC",
            params,
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_by_id(asset_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute("SELECT * FROM asset_copy_packs WHERE id = %s", (asset_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create(*, name: str, primary_text: str = "", headline: str = "",
           description: str = "", language: str = "", product_name: str = "",
           channel: str = "", country_tags: list | None = None,
           theme_tags: list | None = None, remark: str = "",
           created_by: str = "", org_id: str = "") -> dict:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute(
            """INSERT INTO asset_copy_packs
               (org_id, name, primary_text, headline, description, language,
                product_name, channel, country_tags, theme_tags, remark, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (org_id, name, primary_text, headline, description, language,
             product_name, channel,
             json.dumps(country_tags or [], ensure_ascii=False),
             json.dumps(theme_tags or [], ensure_ascii=False),
             remark, created_by),
        )
        new_id = cur.lastrowid
        conn.commit()
    return get_by_id(new_id)  # type: ignore


def update(asset_id: int, **kwargs) -> Optional[dict]:
    allowed = {"name", "primary_text", "headline", "description", "language",
               "product_name", "channel", "country_tags", "theme_tags", "remark", "status"}
    set_parts, values = [], []
    for k, v in kwargs.items():
        if k not in allowed or v is None:
            continue
        if k in ("country_tags", "theme_tags"):
            set_parts.append(f"{k} = %s")
            values.append(json.dumps(v, ensure_ascii=False))
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    if not set_parts:
        return get_by_id(asset_id)
    values.append(asset_id)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute(
            f"UPDATE asset_copy_packs SET {', '.join(set_parts)} WHERE id = %s",
            values,
        )
        conn.commit()
    return get_by_id(asset_id)


def delete(asset_id: int) -> bool:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute("DELETE FROM asset_copy_packs WHERE id = %s", (asset_id,))
        conn.commit()
        return cur.rowcount > 0


def toggle_status(asset_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_copy_packs')
        cur.execute(
            "UPDATE asset_copy_packs SET status = IF(status='active','inactive','active') WHERE id = %s",
            (asset_id,),
        )
        conn.commit()
    return get_by_id(asset_id)
