"""Persistence for application-scoped upload sessions."""
from __future__ import annotations

import json
from typing import Any

from core.isolation import require_scope
from db import get_app_conn


def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    if isinstance(result.get("event_payload"), str):
        result["event_payload"] = json.loads(result["event_payload"])
    return result


def get_version_for_upload(material_id: int, version_id: int) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT v.* FROM material_versions v
               JOIN material_masters m ON m.id=v.material_id AND m.tenant_id=v.tenant_id
               WHERE v.tenant_id=%s AND v.material_id=%s AND v.id=%s""",
            (scope.tenant_id, material_id, version_id),
        )
        return _decode(cur.fetchone())


def find_by_idempotency(key: str) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM app_material_uploads WHERE tenant_id=%s AND application_id=%s AND idempotency_key=%s",
            (scope.tenant_id, scope.application_id, key),
        )
        return _decode(cur.fetchone())


def create_upload(values: dict[str, Any], parts: int) -> dict:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_material_uploads
               (id,tenant_id,application_id,material_id,version_id,idempotency_key,upload_mode,status,
                storage_backend,storage_key,expected_size_bytes,expected_mime_type,expected_checksum_sha256,
                part_size_bytes,part_count,created_by,expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'prepared',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (values["id"], scope.tenant_id, scope.application_id, values["material_id"], values["version_id"],
             values["idempotency_key"], values["upload_mode"], values["storage_backend"], values["storage_key"],
             values["expected_size_bytes"], values["expected_mime_type"], values["expected_checksum_sha256"],
             values.get("part_size_bytes"), parts or None, values["created_by"], values["expires_at"]),
        )
        if parts:
            cur.executemany(
                """INSERT INTO app_material_upload_parts
                   (tenant_id,application_id,upload_id,part_number) VALUES (%s,%s,%s,%s)""",
                [(scope.tenant_id, scope.application_id, values["id"], number) for number in range(1, parts + 1)],
            )
        _audit(cur, values["id"], "prepared", None, "prepared", {"mode": values["upload_mode"]}, values["created_by"])
        conn.commit()
    return get_upload(values["id"])  # type: ignore[return-value]


def get_upload(upload_id: str, *, lock: bool = False, connection=None) -> dict | None:
    scope = require_scope(application=True)
    def query(conn):
        cur = conn.cursor()
        suffix = " FOR UPDATE" if lock else ""
        cur.execute(
            "SELECT * FROM app_material_uploads WHERE tenant_id=%s AND application_id=%s AND id=%s" + suffix,
            (scope.tenant_id, scope.application_id, upload_id),
        )
        return _decode(cur.fetchone())
    if connection is not None:
        return query(connection)
    with get_app_conn() as conn:
        return query(conn)


def list_uploads(material_id: int | None = None) -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        where = "tenant_id=%s AND application_id=%s"
        args: list[Any] = [scope.tenant_id, scope.application_id]
        if material_id is not None:
            where += " AND material_id=%s"; args.append(material_id)
        cur.execute(f"SELECT * FROM app_material_uploads WHERE {where} ORDER BY created_at DESC", args)
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def list_parts(upload_id: str) -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT part_number,size_bytes,checksum_sha256,status,uploaded_at
               FROM app_material_upload_parts WHERE tenant_id=%s AND application_id=%s AND upload_id=%s
               ORDER BY part_number""",
            (scope.tenant_id, scope.application_id, upload_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]


def record_part(upload_id: str, part_number: int, size: int, checksum: str, username: str) -> bool:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_material_upload_parts p
               JOIN app_material_uploads u ON u.id=p.upload_id AND u.tenant_id=p.tenant_id AND u.application_id=p.application_id
               SET p.size_bytes=%s,p.checksum_sha256=%s,p.status='uploaded',p.uploaded_at=NOW(),u.status='uploading'
               WHERE p.tenant_id=%s AND p.application_id=%s AND p.upload_id=%s AND p.part_number=%s
                 AND u.status IN ('prepared','uploading') AND u.expires_at>NOW()""",
            (size, checksum, scope.tenant_id, scope.application_id, upload_id, part_number),
        )
        changed = cur.rowcount
        if changed:
            cur.execute(
                """UPDATE material_versions v JOIN app_material_uploads u
                   ON u.version_id=v.id AND u.tenant_id=v.tenant_id AND u.material_id=v.material_id
                   SET v.upload_status='uploading',v.upload_error=NULL
                   WHERE u.tenant_id=%s AND u.application_id=%s AND u.id=%s AND v.upload_status<>'uploaded'""",
                (scope.tenant_id, scope.application_id, upload_id),
            )
            _audit(cur, upload_id, "part_uploaded", None, "uploading", {"part_number": part_number, "size_bytes": size}, username)
        conn.commit()
        return changed == 1


def mark_direct_received(upload_id: str, size: int, username: str) -> bool:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_material_uploads SET status='uploading',received_size_bytes=%s,error_code=NULL,error_message=NULL
               WHERE tenant_id=%s AND application_id=%s AND id=%s AND upload_mode='direct'
                 AND status IN ('prepared','uploading') AND expires_at>NOW()""",
            (size, scope.tenant_id, scope.application_id, upload_id),
        )
        if cur.rowcount:
            cur.execute(
                """UPDATE material_versions v JOIN app_material_uploads u
                   ON u.version_id=v.id AND u.tenant_id=v.tenant_id AND u.material_id=v.material_id
                   SET v.upload_status='uploading',v.upload_error=NULL
                   WHERE u.tenant_id=%s AND u.application_id=%s AND u.id=%s AND v.upload_status<>'uploaded'""",
                (scope.tenant_id, scope.application_id, upload_id),
            )
            _audit(cur, upload_id, "bytes_received", None, "uploading", {"size_bytes": size}, username)
        conn.commit()
        return cur.rowcount == 1


def finalize(upload_id: str, *, size: int, checksum: str, backend: str, storage_key: str, username: str) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        conn.begin()
        cur = conn.cursor()
        row = get_upload(upload_id, lock=True, connection=conn)
        if not row:
            conn.rollback(); return None
        if row["status"] == "uploaded":
            conn.commit(); return row
        cur.execute(
            """UPDATE app_material_uploads SET status='uploaded',received_size_bytes=%s,
               verified_checksum_sha256=%s,error_code=NULL,error_message=NULL,completed_at=NOW()
               WHERE tenant_id=%s AND application_id=%s AND id=%s""",
            (size, checksum, scope.tenant_id, scope.application_id, upload_id),
        )
        cur.execute(
            """UPDATE material_versions SET upload_status='uploaded',storage_backend=%s,storage_key=%s,
               checksum_sha256=%s,upload_error=NULL
               WHERE tenant_id=%s AND material_id=%s AND id=%s""",
            (backend, storage_key, checksum, scope.tenant_id, row["material_id"], row["version_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback(); return None
        _audit(cur, upload_id, "verified", row["status"], "uploaded", {"size_bytes": size, "checksum_sha256": checksum}, username)
        conn.commit()
    return get_upload(upload_id)


def mark_failed(upload_id: str, code: str, message: str, username: str) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        row = get_upload(upload_id, connection=conn)
        if not row or row["status"] == "uploaded":
            return row
        cur.execute(
            """UPDATE app_material_uploads SET status='failed',error_code=%s,error_message=%s
               WHERE tenant_id=%s AND application_id=%s AND id=%s""",
            (code, message[:1000], scope.tenant_id, scope.application_id, upload_id),
        )
        cur.execute(
            """UPDATE material_versions SET upload_status='failed',upload_error=%s
               WHERE tenant_id=%s AND material_id=%s AND id=%s AND upload_status<>'uploaded'""",
            (message[:1000], scope.tenant_id, row["material_id"], row["version_id"]),
        )
        _audit(cur, upload_id, "failed", row["status"], "failed", {"code": code, "message": message[:500]}, username)
        conn.commit()
    return get_upload(upload_id)


def retry(upload_id: str, expires_at, username: str) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_material_uploads SET status='prepared',attempt_count=attempt_count+1,
               error_code=NULL,error_message=NULL,expires_at=%s
               WHERE tenant_id=%s AND application_id=%s AND id=%s AND status IN ('failed','expired')""",
            (expires_at, scope.tenant_id, scope.application_id, upload_id),
        )
        if cur.rowcount:
            cur.execute("UPDATE app_material_upload_parts SET status='pending',size_bytes=0,checksum_sha256=NULL,uploaded_at=NULL WHERE tenant_id=%s AND application_id=%s AND upload_id=%s", (scope.tenant_id, scope.application_id, upload_id))
            _audit(cur, upload_id, "retried", "failed", "prepared", {}, username)
        conn.commit()
    return get_upload(upload_id) if cur.rowcount else None


def mark_expired(upload_id: str, username: str = "system") -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        row = get_upload(upload_id, connection=conn)
        if not row or row["status"] in {"uploaded", "failed", "expired"}:
            return row
        cur.execute(
            """UPDATE app_material_uploads SET status='expired',error_code='session_expired',
               error_message='上传会话已过期' WHERE tenant_id=%s AND application_id=%s AND id=%s AND expires_at<=NOW()""",
            (scope.tenant_id, scope.application_id, upload_id),
        )
        if cur.rowcount:
            cur.execute(
                """UPDATE material_versions SET upload_status='failed',upload_error='上传会话已过期'
                   WHERE tenant_id=%s AND material_id=%s AND id=%s AND upload_status<>'uploaded'""",
                (scope.tenant_id, row["material_id"], row["version_id"]),
            )
            _audit(cur, upload_id, "expired", row["status"], "expired", {}, username)
        conn.commit()
    return get_upload(upload_id)


def _audit(cur, upload_id: str, event: str, before: str | None, after: str | None, payload: dict, username: str) -> None:
    scope = require_scope(application=True)
    cur.execute(
        """INSERT INTO app_material_upload_audit
           (tenant_id,application_id,upload_id,event_type,from_status,to_status,event_payload,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (scope.tenant_id, scope.application_id, upload_id, event, before, after, json.dumps(payload, ensure_ascii=False), username),
    )
