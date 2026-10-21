"""Application-scoped persistence for mappings and immutable preflight runs."""
from __future__ import annotations

import json
import uuid

from core.isolation import require_scope, tenant_cursor
from db import get_app_conn


JSON_FIELDS = ("blocking_reasons", "dry_run_plan")


def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    for field in JSON_FIELDS:
        if isinstance(result.get(field), str):
            result[field] = json.loads(result[field])
    for field in ("created_at", "updated_at", "finished_at"):
        if result.get(field) is not None:
            result[field] = str(result[field])
    for field in ("dry_run", "external_write_authorized"):
        if field in result:
            result[field] = bool(result[field])
    return result


def upsert_account_mapping(values: dict, created_by: str) -> dict:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_platform_account_mappings
               (tenant_id,application_id,platform,account_id,external_account_id,
                credential_external_id,status,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE external_account_id=VALUES(external_account_id),
                 credential_external_id=VALUES(credential_external_id),status=VALUES(status)""",
            (scope.tenant_id, scope.application_id, values["platform"], values["account_id"],
             values["external_account_id"], values["credential_external_id"], values["status"], created_by),
        )
        conn.commit()
    return get_account_mapping(values["platform"], values["account_id"])  # type: ignore[return-value]


def get_account_mapping(platform: str, account_id: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_account_mappings")
        cur.execute("SELECT * FROM app_platform_account_mappings WHERE platform=%s AND account_id=%s", (platform, account_id))
        return _decode(cur.fetchone())


def list_account_mappings() -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_account_mappings")
        cur.execute("SELECT * FROM app_platform_account_mappings ORDER BY platform, account_id")
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def upsert_material_mapping(values: dict, created_by: str) -> dict:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_platform_material_mappings
               (tenant_id,application_id,platform,account_id,material_id,version_id,
                platform_asset_id,upload_status,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE platform_asset_id=VALUES(platform_asset_id),
                 upload_status=VALUES(upload_status)""",
            (scope.tenant_id, scope.application_id, values["platform"], values["account_id"],
             values["material_id"], values["version_id"], values["platform_asset_id"],
             values["upload_status"], created_by),
        )
        conn.commit()
    return get_material_mapping(values["platform"], values["account_id"], values["material_id"], values["version_id"])  # type: ignore[return-value]


def get_material_mapping(platform: str, account_id: str, material_id: int, version_id: int) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_material_mappings")
        cur.execute(
            """SELECT * FROM app_platform_material_mappings
               WHERE platform=%s AND account_id=%s AND material_id=%s AND version_id=%s""",
            (platform, account_id, material_id, version_id),
        )
        return _decode(cur.fetchone())


def list_material_mappings() -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_material_mappings")
        cur.execute("SELECT * FROM app_platform_material_mappings ORDER BY platform, account_id, material_id, version_id")
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def get_run(run_id: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_preflight_runs")
        cur.execute("SELECT * FROM app_platform_preflight_runs WHERE id=%s", (run_id,))
        return _decode(cur.fetchone())


def get_run_by_request(request_key: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_preflight_runs")
        cur.execute("SELECT * FROM app_platform_preflight_runs WHERE request_key=%s", (request_key,))
        return _decode(cur.fetchone())


def list_runs(draft_id: str | None = None) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_preflight_runs")
        if draft_id:
            cur.execute("SELECT * FROM app_platform_preflight_runs WHERE draft_id=%s ORDER BY created_at DESC, id DESC", (draft_id,))
        else:
            cur.execute("SELECT * FROM app_platform_preflight_runs ORDER BY created_at DESC, id DESC")
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def create_run(*, draft_id: str, request_key: str, snapshot_hash: str, status: str,
               blockers: list[dict], plan: dict, plan_hash: str, execution_key: str,
               created_by: str) -> tuple[dict, bool]:
    run_id = str(uuid.uuid4())
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT IGNORE INTO app_platform_preflight_runs
               (id,tenant_id,application_id,draft_id,request_key,snapshot_hash,status,
                blocking_reasons,dry_run_plan,plan_hash,execution_key,dry_run,
                external_write_authorized,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s)""",
            (run_id, scope.tenant_id, scope.application_id, draft_id, request_key,
             snapshot_hash, status, json.dumps(blockers, ensure_ascii=False, sort_keys=True),
             json.dumps(plan, ensure_ascii=False, sort_keys=True), plan_hash, execution_key, created_by),
        )
        inserted = cur.rowcount == 1
        if inserted:
            cur.execute(
                """INSERT INTO app_platform_preflight_audit
                   (tenant_id,application_id,run_id,event_type,event_payload,created_by)
                   VALUES (%s,%s,%s,'preflight.completed',%s,%s)""",
                (scope.tenant_id, scope.application_id, run_id,
                 json.dumps({"status": status, "plan_hash": plan_hash, "blocking_count": len(blockers),
                             "dry_run": True, "external_write_authorized": False}, ensure_ascii=False, sort_keys=True),
                 created_by),
            )
        conn.commit()
    return (get_run(run_id) if inserted else get_run_by_request(request_key)), inserted  # type: ignore[return-value]


def list_audit(run_id: str) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_platform_preflight_audit")
        cur.execute("SELECT * FROM app_platform_preflight_audit WHERE run_id=%s ORDER BY id", (run_id,))
        rows = []
        for raw in cur.fetchall() or []:
            row = dict(raw)
            if isinstance(row.get("event_payload"), str):
                row["event_payload"] = json.loads(row["event_payload"])
            row["created_at"] = str(row["created_at"])
            rows.append(row)
        return rows


def append_audit(run_id: str, event_type: str, payload: dict, created_by: str) -> None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_platform_preflight_audit
               (tenant_id,application_id,run_id,event_type,event_payload,created_by)
               SELECT %s,%s,id,%s,%s,%s FROM app_platform_preflight_runs
               WHERE id=%s AND tenant_id=%s AND application_id=%s""",
            (scope.tenant_id, scope.application_id, event_type,
             json.dumps(payload, ensure_ascii=False, sort_keys=True), created_by,
             run_id, scope.tenant_id, scope.application_id),
        )
        if cur.rowcount != 1:
            raise LookupError("预检记录不存在于当前应用")
        conn.commit()
