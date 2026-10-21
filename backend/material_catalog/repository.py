"""Explicit tenant/application scoped persistence for the material catalog."""
from __future__ import annotations

import json
from typing import Any

from core.isolation import require_scope
from db import get_app_conn


def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    for field in ("tags", "metadata_json"):
        if isinstance(result.get(field), str):
            result[field] = json.loads(result[field])
    return result


def get_drama(drama_id: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title FROM drama_masters WHERE tenant_id=%s AND id=%s", (scope.tenant_id, drama_id))
        return cur.fetchone()


def create_master(values: dict[str, Any]) -> dict:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO material_masters
               (tenant_id, drama_id, name, material_type, description, tags, status, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (scope.tenant_id, values["drama_id"], values["name"], values["material_type"],
             values["description"], json.dumps(values["tags"], ensure_ascii=False), values["status"], values["created_by"]),
        )
        material_id = cur.lastrowid
        conn.commit()
    return get_master(material_id)  # type: ignore[return-value]


def get_master(material_id: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT m.*, d.title AS drama_title FROM material_masters m
               LEFT JOIN drama_masters d ON d.id=m.drama_id AND d.tenant_id=m.tenant_id
               WHERE m.tenant_id=%s AND m.id=%s""", (scope.tenant_id, material_id),
        )
        return _decode(cur.fetchone())


def list_masters(query: str, status: str, page: int, page_size: int) -> dict:
    scope = require_scope()
    where = "m.tenant_id=%s"
    args: list[Any] = [scope.tenant_id]
    if query:
        where += " AND (m.name LIKE %s OR JSON_SEARCH(m.tags, 'one', %s) IS NOT NULL)"
        args.extend((f"%{query}%", f"%{query}%"))
    if status:
        where += " AND m.status=%s"
        args.append(status)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS total FROM material_masters m WHERE {where}", args)
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""SELECT m.*, d.title AS drama_title FROM material_masters m
                LEFT JOIN drama_masters d ON d.id=m.drama_id AND d.tenant_id=m.tenant_id
                WHERE {where} ORDER BY m.updated_at DESC, m.id DESC LIMIT %s OFFSET %s""",
            [*args, page_size, (page - 1) * page_size],
        )
        return {"items": [_decode(row) for row in (cur.fetchall() or [])], "total": total, "page": page, "page_size": page_size}


def update_master(material_id: int, values: dict[str, Any], revision: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE material_masters SET drama_id=%s, name=%s, material_type=%s,
               description=%s, tags=%s, status=%s, revision=revision+1
               WHERE tenant_id=%s AND id=%s AND revision=%s""",
            (values["drama_id"], values["name"], values["material_type"], values["description"],
             json.dumps(values["tags"], ensure_ascii=False), values["status"], scope.tenant_id, material_id, revision),
        )
        changed = cur.rowcount
        conn.commit()
    return get_master(material_id) if changed else None


def create_version(material_id: int, values: dict[str, Any]) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute("SELECT latest_version_number FROM material_masters WHERE tenant_id=%s AND id=%s FOR UPDATE", (scope.tenant_id, material_id))
            master = cur.fetchone()
            if not master:
                conn.rollback()
                return None
            number = int(master["latest_version_number"]) + 1
            cur.execute(
                """INSERT INTO material_versions
                   (tenant_id, material_id, version_number, source_filename, file_extension,
                    mime_type, size_bytes, checksum_sha256, width, height, duration_ms,
                    metadata_json, notes, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (scope.tenant_id, material_id, number, values["source_filename"], values["file_extension"],
                 values["mime_type"], values["size_bytes"], values["checksum_sha256"], values["width"],
                 values["height"], values["duration_ms"], json.dumps(values["metadata_json"], ensure_ascii=False),
                 values["notes"], values["created_by"]),
            )
            version_id = cur.lastrowid
            cur.execute("UPDATE material_masters SET latest_version_number=%s WHERE tenant_id=%s AND id=%s", (number, scope.tenant_id, material_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_version(material_id, version_id)


def get_version(material_id: int, version_id: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM material_versions WHERE tenant_id=%s AND material_id=%s AND id=%s", (scope.tenant_id, material_id, version_id))
        return _decode(cur.fetchone())


def list_versions(material_id: int) -> list[dict] | None:
    if not get_master(material_id):
        return None
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM material_versions WHERE tenant_id=%s AND material_id=%s ORDER BY version_number DESC", (scope.tenant_id, material_id))
        return [_decode(row) for row in (cur.fetchall() or [])]  # type: ignore[misc]


def attach(material_id: int, values: dict[str, Any]) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_application_materials
               (tenant_id, application_id, material_id, selected_version_id, selection_mode, status, notes, created_by)
               SELECT %s,%s,m.id,v.id,%s,%s,%s,%s FROM material_masters m
               LEFT JOIN material_versions v ON v.id=%s AND v.tenant_id=m.tenant_id AND v.material_id=m.id
               WHERE m.tenant_id=%s AND m.id=%s AND (%s IS NULL OR v.id IS NOT NULL)""",
            (scope.tenant_id, scope.application_id, values["selection_mode"], values["status"],
             values["notes"], values["created_by"], values["selected_version_id"], scope.tenant_id, material_id, values["selected_version_id"]),
        )
        changed = cur.rowcount
        conn.commit()
    return get_reference(material_id) if changed == 1 else None


def get_reference(material_id: int) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.id AS reference_id, r.application_id, r.material_id, r.selected_version_id,
                      r.selection_mode, r.status AS reference_status, r.notes, m.name, m.material_type,
                      m.drama_id, m.latest_version_number, v.version_number AS selected_version_number,
                      v.upload_status AS selected_version_upload_status
               FROM app_application_materials r
               JOIN material_masters m ON m.id=r.material_id AND m.tenant_id=r.tenant_id
               LEFT JOIN material_versions v ON v.id=r.selected_version_id AND v.tenant_id=r.tenant_id AND v.material_id=r.material_id
               WHERE r.tenant_id=%s AND r.application_id=%s AND r.material_id=%s""",
            (scope.tenant_id, scope.application_id, material_id),
        )
        return _decode(cur.fetchone())


def list_references(page: int, page_size: int) -> dict:
    scope = require_scope(application=True)
    where = "r.tenant_id=%s AND r.application_id=%s"
    args = [scope.tenant_id, scope.application_id]
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS total FROM app_application_materials r WHERE {where}", args)
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""SELECT r.id AS reference_id, r.application_id, r.material_id, r.selected_version_id,
                       r.selection_mode, r.status AS reference_status, r.notes, m.name, m.material_type,
                       m.drama_id, m.latest_version_number, v.version_number AS selected_version_number,
                       v.upload_status AS selected_version_upload_status
                FROM app_application_materials r JOIN material_masters m ON m.id=r.material_id AND m.tenant_id=r.tenant_id
                LEFT JOIN material_versions v ON v.id=r.selected_version_id AND v.tenant_id=r.tenant_id AND v.material_id=r.material_id
                WHERE {where} ORDER BY r.updated_at DESC, r.id DESC LIMIT %s OFFSET %s""",
            [*args, page_size, (page - 1) * page_size],
        )
        return {"items": [_decode(row) for row in (cur.fetchall() or [])], "total": total, "page": page, "page_size": page_size}


def update_reference(material_id: int, values: dict[str, Any]) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_application_materials r
               LEFT JOIN material_versions v ON v.id=%s AND v.tenant_id=r.tenant_id AND v.material_id=r.material_id
               SET r.selected_version_id=%s, r.selection_mode=%s, r.status=%s, r.notes=%s
               WHERE r.tenant_id=%s AND r.application_id=%s AND r.material_id=%s
                 AND (%s IS NULL OR v.id IS NOT NULL)""",
            (values["selected_version_id"], values["selected_version_id"], values["selection_mode"], values["status"],
             values["notes"], scope.tenant_id, scope.application_id, material_id, values["selected_version_id"]),
        )
        conn.commit()
    return get_reference(material_id)


def detach(material_id: int) -> bool:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM app_application_materials WHERE tenant_id=%s AND application_id=%s AND material_id=%s", (scope.tenant_id, scope.application_id, material_id))
        changed = cur.rowcount
        conn.commit()
    return changed == 1
