"""Persistence for immutable rule versions and deterministic evaluations."""
from __future__ import annotations

import json
import uuid

from core.isolation import require_scope, tenant_cursor
from db import get_app_conn


JSON_FIELDS = ("definition", "input_snapshot", "blocking_reasons", "evidence", "event_payload")


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


def list_rules() -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.*, v.id AS rule_version_id, v.definition, v.definition_hash
               FROM app_automation_rules r
               JOIN app_automation_rule_versions v
                 ON v.tenant_id=r.tenant_id AND v.application_id=r.application_id
                AND v.rule_id=r.id AND v.version=r.current_version
               WHERE r.tenant_id=%s AND r.application_id=%s
               ORDER BY r.updated_at DESC, r.id DESC""",
            (scope.tenant_id, scope.application_id),
        )
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def get_rule(rule_id: str, version: int | None = None) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        if version is None:
            cur.execute(
                """SELECT r.*, v.id AS rule_version_id, v.definition, v.definition_hash
                   FROM app_automation_rules r
                   JOIN app_automation_rule_versions v
                     ON v.tenant_id=r.tenant_id AND v.application_id=r.application_id
                    AND v.rule_id=r.id AND v.version=r.current_version
                   WHERE r.tenant_id=%s AND r.application_id=%s AND r.id=%s""",
                (scope.tenant_id, scope.application_id, rule_id),
            )
        else:
            cur.execute(
                """SELECT r.*, v.id AS rule_version_id, v.version AS selected_version,
                          v.definition, v.definition_hash
                   FROM app_automation_rules r
                   JOIN app_automation_rule_versions v
                     ON v.tenant_id=r.tenant_id AND v.application_id=r.application_id
                    AND v.rule_id=r.id
                   WHERE r.tenant_id=%s AND r.application_id=%s AND r.id=%s AND v.version=%s""",
                (scope.tenant_id, scope.application_id, rule_id, version),
            )
        return _decode(cur.fetchone())


def list_versions(rule_id: str) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_versions")
        cur.execute(
            "SELECT * FROM app_automation_rule_versions WHERE rule_id=%s ORDER BY version DESC",
            (rule_id,),
        )
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def create_rule(*, name: str, description: str, status: str, definition: dict,
                definition_hash: str, created_by: str) -> dict:
    scope = require_scope(application=True)
    rule_id = str(uuid.uuid4())
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO app_automation_rules
                   (id,tenant_id,application_id,name,description,status,current_version,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,1,%s)""",
                (rule_id, scope.tenant_id, scope.application_id, name, description, status, created_by),
            )
            cur.execute(
                """INSERT INTO app_automation_rule_versions
                   (tenant_id,application_id,rule_id,version,definition,definition_hash,created_by)
                   VALUES (%s,%s,%s,1,%s,%s,%s)""",
                (scope.tenant_id, scope.application_id, rule_id,
                 json.dumps(definition, ensure_ascii=False, sort_keys=True), definition_hash, created_by),
            )
            _append_audit(cur, scope.tenant_id, scope.application_id, "rule", rule_id,
                          "rule.created", {"version": 1, "definition_hash": definition_hash, "status": status}, created_by)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_rule(rule_id)  # type: ignore[return-value]


def create_version(rule_id: str, *, expected_version: int, name: str, description: str,
                   status: str, definition: dict, definition_hash: str, created_by: str) -> dict | None:
    scope = require_scope(application=True)
    next_version = expected_version + 1
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE app_automation_rules
                   SET name=%s,description=%s,status=%s,current_version=%s
                   WHERE id=%s AND tenant_id=%s AND application_id=%s AND current_version=%s""",
                (name, description, status, next_version, rule_id,
                 scope.tenant_id, scope.application_id, expected_version),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            cur.execute(
                """INSERT INTO app_automation_rule_versions
                   (tenant_id,application_id,rule_id,version,definition,definition_hash,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (scope.tenant_id, scope.application_id, rule_id, next_version,
                 json.dumps(definition, ensure_ascii=False, sort_keys=True), definition_hash, created_by),
            )
            _append_audit(cur, scope.tenant_id, scope.application_id, "rule", rule_id,
                          "rule.version_created", {"version": next_version, "definition_hash": definition_hash, "status": status}, created_by)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_rule(rule_id)


def get_evaluation(evaluation_id: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_evaluations")
        cur.execute("SELECT * FROM app_automation_rule_evaluations WHERE id=%s", (evaluation_id,))
        row = _decode(cur.fetchone())
    if row:
        row["recommendations"] = list_recommendations(evaluation_id)
    return row


def get_evaluation_by_key(evaluation_key: str) -> dict | None:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_evaluations")
        cur.execute("SELECT id FROM app_automation_rule_evaluations WHERE evaluation_key=%s", (evaluation_key,))
        row = cur.fetchone()
    return get_evaluation(row["id"]) if row else None


def list_evaluations(rule_id: str | None = None) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_evaluations")
        if rule_id:
            cur.execute("SELECT * FROM app_automation_rule_evaluations WHERE rule_id=%s ORDER BY created_at DESC,id DESC", (rule_id,))
        else:
            cur.execute("SELECT * FROM app_automation_rule_evaluations ORDER BY created_at DESC,id DESC")
        rows = [_decode(row) for row in (cur.fetchall() or [])]
    for row in rows:
        row["recommendations"] = list_recommendations(row["id"])
    return rows  # type: ignore[return-value]


def list_recommendations(evaluation_id: str) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_recommendations")
        cur.execute("SELECT * FROM app_automation_rule_recommendations WHERE evaluation_id=%s ORDER BY id", (evaluation_id,))
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def create_evaluation(*, rule: dict, input_snapshot: dict, input_snapshot_hash: str,
                      evaluation_key: str, status: str, blockers: list[dict],
                      recommendations: list[dict], created_by: str) -> tuple[dict, bool]:
    scope = require_scope(application=True)
    evaluation_id = str(uuid.uuid4())
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT IGNORE INTO app_automation_rule_evaluations
                   (id,tenant_id,application_id,rule_id,rule_version_id,input_snapshot,
                    input_snapshot_hash,evaluation_key,status,blocking_reasons,dry_run,
                    external_write_authorized,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s)""",
                (evaluation_id, scope.tenant_id, scope.application_id, rule["id"], rule["rule_version_id"],
                 json.dumps(input_snapshot, ensure_ascii=False, sort_keys=True), input_snapshot_hash,
                 evaluation_key, status, json.dumps(blockers, ensure_ascii=False, sort_keys=True), created_by),
            )
            inserted = cur.rowcount == 1
            if inserted:
                for item in recommendations:
                    cur.execute(
                        """INSERT INTO app_automation_rule_recommendations
                           (tenant_id,application_id,evaluation_id,outcome,reason_code,reason_message,evidence)
                           VALUES (%s,%s,%s,'review_required',%s,%s,%s)""",
                        (scope.tenant_id, scope.application_id, evaluation_id, item["code"], item["message"],
                         json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True)),
                    )
                _append_audit(cur, scope.tenant_id, scope.application_id, "evaluation", evaluation_id,
                              "evaluation.completed", {"rule_id": rule["id"], "rule_version": rule["current_version"],
                              "input_snapshot_hash": input_snapshot_hash, "status": status,
                              "recommendation_count": len(recommendations), "blocking_count": len(blockers),
                              "dry_run": True, "external_write_authorized": False}, created_by)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    row = get_evaluation(evaluation_id) if inserted else get_evaluation_by_key(evaluation_key)
    return row, inserted  # type: ignore[return-value]


def list_audit(entity_type: str, entity_id: str) -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, "app_automation_rule_audit")
        cur.execute(
            "SELECT * FROM app_automation_rule_audit WHERE entity_type=%s AND entity_id=%s ORDER BY id",
            (entity_type, entity_id),
        )
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def _append_audit(cur, tenant_id: int, application_id: int, entity_type: str,
                  entity_id: str, event_type: str, payload: dict, created_by: str) -> None:
    cur.execute(
        """INSERT INTO app_automation_rule_audit
           (tenant_id,application_id,entity_type,entity_id,event_type,event_payload,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (tenant_id, application_id, entity_type, entity_id, event_type,
         json.dumps(payload, ensure_ascii=False, sort_keys=True), created_by),
    )
