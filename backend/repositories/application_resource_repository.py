"""Fail-closed CRUD for application-owned configuration resources.

These repositories intentionally share one narrow implementation so every
primary-key read/write and list receives the same tenant+application predicate.
The table name is selected only from a static allow-list.
"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import tenant_cursor
from db import get_app_conn


RESOURCE_TABLES = {
    "account_group": ("app_account_groups", "account_refs"),
    "creative_group": ("app_creative_groups", "asset_refs"),
    "naming_rule": ("app_naming_rules", "rule"),
}


def _spec(kind: str) -> tuple[str, str]:
    try:
        return RESOURCE_TABLES[kind]
    except KeyError as exc:
        raise ValueError("不支持的应用资源类型") from exc


def _decode(row: Optional[dict], payload_column: str) -> Optional[dict]:
    if not row:
        return None
    row = dict(row)
    if isinstance(row.get(payload_column), str):
        row[payload_column] = json.loads(row[payload_column])
    return row


def create(kind: str, *, name: str, payload: object, created_by: str = "") -> dict:
    table, payload_column = _spec(kind)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, table)
        cur.execute(
            f"INSERT INTO {table} (name, {payload_column}, created_by) VALUES (%s, %s, %s)",
            (name, json.dumps(payload, ensure_ascii=False), created_by),
        )
        resource_id = cur.lastrowid
        conn.commit()
    return get(kind, resource_id)  # type: ignore[return-value]


def get(kind: str, resource_id: int) -> Optional[dict]:
    table, payload_column = _spec(kind)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, table)
        cur.execute(f"SELECT * FROM {table} WHERE id=%s", (resource_id,))
        return _decode(cur.fetchone(), payload_column)


def list_all(kind: str) -> list[dict]:
    table, payload_column = _spec(kind)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, table)
        cur.execute(f"SELECT * FROM {table} ORDER BY id")
        return [_decode(row, payload_column) for row in cur.fetchall()]  # type: ignore[misc]


def update(kind: str, resource_id: int, *, name: str, payload: object) -> Optional[dict]:
    table, payload_column = _spec(kind)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, table)
        cur.execute(
            f"UPDATE {table} SET name=%s, {payload_column}=%s WHERE id=%s",
            (name, json.dumps(payload, ensure_ascii=False), resource_id),
        )
        changed = cur.rowcount
        conn.commit()
    return get(kind, resource_id) if changed else None


def delete(kind: str, resource_id: int) -> bool:
    table, _ = _spec(kind)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, table)
        cur.execute(f"DELETE FROM {table} WHERE id=%s", (resource_id,))
        changed = cur.rowcount
        conn.commit()
    return changed == 1
