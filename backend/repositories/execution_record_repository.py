"""Application-scoped platform execution records."""
from __future__ import annotations

import json
import uuid

from core.isolation import tenant_cursor
from db import get_app_conn


def create(*, operation: str, target_type: str = "", target_id: str = "",
           request_payload: dict | None = None, created_by: str = "") -> dict:
    record_id = str(uuid.uuid4())
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_execution_records")
        cur.execute(
            """INSERT INTO app_execution_records
               (id, operation, target_type, target_id, request_payload, created_by)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (record_id, operation, target_type, target_id,
             json.dumps(request_payload, ensure_ascii=False) if request_payload is not None else None,
             created_by),
        )
        conn.commit()
    return get(record_id)  # type: ignore[return-value]


def _decode(row):
    if not row:
        return None
    row = dict(row)
    for column in ("request_payload", "result"):
        if isinstance(row.get(column), str):
            row[column] = json.loads(row[column])
    return row


def get(record_id: str):
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_execution_records")
        cur.execute("SELECT * FROM app_execution_records WHERE id=%s", (record_id,))
        return _decode(cur.fetchone())


def list_all() -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_execution_records")
        cur.execute("SELECT * FROM app_execution_records ORDER BY created_at DESC, id")
        return [_decode(row) for row in cur.fetchall()]


def finish(record_id: str, *, status: str, result: dict | None = None,
           error_message: str | None = None):
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_execution_records")
        cur.execute(
            """UPDATE app_execution_records
               SET status=%s, result=%s, error_message=%s, finished_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
             error_message, record_id),
        )
        changed = cur.rowcount
        conn.commit()
    return get(record_id) if changed else None
