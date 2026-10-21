"""地区组资产库 — asset_region_groups 表 CRUD"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import tenant_cursor
from db import get_app_conn


def _row_to_dict(row: dict) -> dict:
    cc = row.get("country_codes")
    if isinstance(cc, str):
        cc = json.loads(cc)
    return {
        "id": row["id"],
        "org_id": row.get("org_id", ""),
        "name": row.get("name", ""),
        "country_codes": cc or [],
        "country_count": row.get("country_count", 0),
        "language_hint": row.get("language_hint", ""),
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
        where.append("name LIKE %s")
        params.append(kw)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute(
            f"SELECT * FROM asset_region_groups WHERE {' AND '.join(where)} ORDER BY id DESC",
            params,
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_by_id(asset_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute("SELECT * FROM asset_region_groups WHERE id = %s", (asset_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create(*, name: str, country_codes: list, language_hint: str = "",
           remark: str = "", created_by: str = "", org_id: str = "") -> dict:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute(
            """INSERT INTO asset_region_groups
               (org_id, name, country_codes, country_count, language_hint, remark, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (org_id, name,
             json.dumps(country_codes, ensure_ascii=False),
             len(country_codes), language_hint, remark, created_by),
        )
        new_id = cur.lastrowid
        conn.commit()
    return get_by_id(new_id)  # type: ignore


def update(asset_id: int, **kwargs) -> Optional[dict]:
    allowed = {"name", "country_codes", "language_hint", "remark", "status"}
    set_parts, values = [], []
    for k, v in kwargs.items():
        if k not in allowed or v is None:
            continue
        if k == "country_codes":
            set_parts.append("country_codes = %s")
            values.append(json.dumps(v, ensure_ascii=False))
            set_parts.append("country_count = %s")
            values.append(len(v))
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    if not set_parts:
        return get_by_id(asset_id)
    values.append(asset_id)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute(
            f"UPDATE asset_region_groups SET {', '.join(set_parts)} WHERE id = %s",
            values,
        )
        conn.commit()
    return get_by_id(asset_id)


def delete(asset_id: int) -> bool:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute("DELETE FROM asset_region_groups WHERE id = %s", (asset_id,))
        conn.commit()
        return cur.rowcount > 0


def toggle_status(asset_id: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'asset_region_groups')
        cur.execute(
            "UPDATE asset_region_groups SET status = IF(status='active','inactive','active') WHERE id = %s",
            (asset_id,),
        )
        conn.commit()
    return get_by_id(asset_id)
