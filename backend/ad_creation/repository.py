"""Persistence for preparation-only ad creation drafts."""
from __future__ import annotations

import json
import uuid

from core.isolation import require_scope, tenant_cursor
from db import get_app_conn


JSON_FIELDS = (
    "naming_values", "resolved_accounts", "name_previews", "creative_snapshot",
    "blocking_reasons", "execution_snapshot",
)


def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    for field in JSON_FIELDS:
        if isinstance(result.get(field), str):
            result[field] = json.loads(result[field])
    for field in ("created_at", "updated_at", "ready_at"):
        if result.get(field) is not None:
            result[field] = str(result[field])
    return result


def get(draft_id: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_ad_creation_drafts")
        cur.execute("SELECT * FROM app_ad_creation_drafts WHERE id=%s", (draft_id,))
        return _decode(cur.fetchone())


def list_all() -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_ad_creation_drafts")
        cur.execute(
            "SELECT * FROM app_ad_creation_drafts ORDER BY updated_at DESC, id DESC"
        )
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def create(*, request_key: str, created_by: str, title: str,
           account_group_id: int, naming_rule_id: int, creative_group_id: int,
           naming_values: dict, resolution: dict) -> tuple[dict, bool]:
    draft_id = str(uuid.uuid4())
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT IGNORE INTO app_ad_creation_drafts
               (id, tenant_id, application_id, created_by, request_key, title, account_group_id,
                naming_rule_id, creative_group_id, naming_values,
                resolved_accounts, name_previews, creative_snapshot, blocking_reasons)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                draft_id, scope.tenant_id, scope.application_id, created_by, request_key, title, account_group_id,
                naming_rule_id, creative_group_id,
                json.dumps(naming_values, ensure_ascii=False, sort_keys=True),
                json.dumps(resolution["resolved_accounts"], ensure_ascii=False),
                json.dumps(resolution["name_previews"], ensure_ascii=False),
                json.dumps(resolution["creative_snapshot"], ensure_ascii=False),
                json.dumps(resolution["blocking_reasons"], ensure_ascii=False),
            ),
        )
        inserted = cur.rowcount == 1
        cur.execute(
            """SELECT * FROM app_ad_creation_drafts
               WHERE tenant_id=%s AND application_id=%s
                 AND created_by=%s AND request_key=%s""",
            (scope.tenant_id, scope.application_id, created_by, request_key),
        )
        row = _decode(cur.fetchone())
        conn.commit()
    return row, inserted  # type: ignore[return-value]


def update(draft_id: str, *, expected_revision: int, title: str,
           account_group_id: int, naming_rule_id: int, creative_group_id: int,
           naming_values: dict, resolution: dict) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_ad_creation_drafts")
        cur.execute(
            """UPDATE app_ad_creation_drafts
               SET title=%s, account_group_id=%s, naming_rule_id=%s,
                   creative_group_id=%s, naming_values=%s, resolved_accounts=%s,
                   name_previews=%s, creative_snapshot=%s, blocking_reasons=%s,
                   revision=revision+1
               WHERE id=%s AND revision=%s AND status='DRAFT'""",
            (
                title, account_group_id, naming_rule_id, creative_group_id,
                json.dumps(naming_values, ensure_ascii=False, sort_keys=True),
                json.dumps(resolution["resolved_accounts"], ensure_ascii=False),
                json.dumps(resolution["name_previews"], ensure_ascii=False),
                json.dumps(resolution["creative_snapshot"], ensure_ascii=False),
                json.dumps(resolution["blocking_reasons"], ensure_ascii=False),
                draft_id, expected_revision,
            ),
        )
        changed = cur.rowcount
        conn.commit()
    return get(draft_id) if changed else None


def refresh(draft_id: str, *, expected_revision: int, resolution: dict) -> dict | None:
    """Persist a read-time readiness result without advancing the edit revision."""
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_ad_creation_drafts")
        cur.execute(
            """UPDATE app_ad_creation_drafts
               SET resolved_accounts=%s, name_previews=%s, creative_snapshot=%s,
                   blocking_reasons=%s
               WHERE id=%s AND revision=%s AND status='DRAFT'""",
            (
                json.dumps(resolution["resolved_accounts"], ensure_ascii=False),
                json.dumps(resolution["name_previews"], ensure_ascii=False),
                json.dumps(resolution["creative_snapshot"], ensure_ascii=False),
                json.dumps(resolution["blocking_reasons"], ensure_ascii=False),
                draft_id, expected_revision,
            ),
        )
        changed = cur.rowcount
        conn.commit()
    return get(draft_id) if changed else None


def mark_ready(draft_id: str, *, expected_revision: int, resolution: dict,
               snapshot: dict, snapshot_hash: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_ad_creation_drafts")
        cur.execute(
            """UPDATE app_ad_creation_drafts
               SET status='READY', revision=revision+1, resolved_accounts=%s,
                   name_previews=%s, creative_snapshot=%s, blocking_reasons=%s,
                   execution_snapshot=%s, execution_snapshot_hash=%s,
                   ready_at=CURRENT_TIMESTAMP
               WHERE id=%s AND revision=%s AND status='DRAFT'""",
            (
                json.dumps(resolution["resolved_accounts"], ensure_ascii=False),
                json.dumps(resolution["name_previews"], ensure_ascii=False),
                json.dumps(resolution["creative_snapshot"], ensure_ascii=False),
                json.dumps(resolution["blocking_reasons"], ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                snapshot_hash, draft_id, expected_revision,
            ),
        )
        changed = cur.rowcount
        conn.commit()
    return get(draft_id) if changed else None
