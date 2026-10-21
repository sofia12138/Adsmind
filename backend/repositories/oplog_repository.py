"""操作日志数据访问层 — 封装 app_oplog 表的所有 SQL 操作"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import tenant_cursor
from db import get_app_conn


def insert(*, username: str, action: str, target_type: str = "",
           target_id: str = "", platform: str = "",
           user_id: int | None = None,
           before_data: dict | None = None, after_data: dict | None = None,
           status: str = "success", error_message: str | None = None) -> int:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_oplog')
        cur.execute(
            """INSERT INTO app_oplog
               (user_id, username, action, target_type, target_id, platform,
                before_data, after_data, status, error_message)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                user_id, username, action, target_type, target_id, platform,
                json.dumps(before_data, ensure_ascii=False) if before_data else None,
                json.dumps(after_data, ensure_ascii=False) if after_data else None,
                status, error_message,
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_logs(page: int = 1, page_size: int = 30) -> tuple[list[dict], int]:
    """返回 (日志列表, 总数)"""
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_oplog')
        cur.execute("SELECT COUNT(*) AS cnt FROM app_oplog")
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * page_size
        cur.execute(
            "SELECT * FROM app_oplog ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            (page_size, offset),
        )
        rows = cur.fetchall()

    for row in rows:
        for field in ("before_data", "after_data"):
            if row.get(field) and isinstance(row[field], str):
                row[field] = json.loads(row[field])
    return rows, total
