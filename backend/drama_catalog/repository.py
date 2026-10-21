"""Explicitly scoped persistence for drama masters and application references."""
from __future__ import annotations

import json
from typing import Any

from core.isolation import require_scope
from db import get_app_conn


def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    for field in ("aliases", "genres"):
        if isinstance(result.get(field), str):
            result[field] = json.loads(result[field])
    result["language"] = result.get("original_language", "")
    return result


def _page(rows: list[dict], total: int, page: int, page_size: int) -> dict:
    return {"items": [_decode(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def create_master(values: dict[str, Any]) -> dict:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO drama_masters
               (tenant_id, catalog_type, title, chinese_title, normalized_title, aliases,
                original_language, launched_at, region, genres, synopsis, cover_url,
                content_fingerprint, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (scope.tenant_id, values["catalog_type"], values["title"], values["chinese_title"],
             values["normalized_title"],
             json.dumps(values["aliases"], ensure_ascii=False), values["original_language"],
             values["launched_at"], values["region"], json.dumps(values["genres"], ensure_ascii=False),
             values["synopsis"], values["cover_url"], values["content_fingerprint"],
             values["created_by"]),
        )
        master_id = cur.lastrowid
        conn.commit()
    return get_master(master_id)  # type: ignore[return-value]


def get_master(master_id: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM drama_masters WHERE tenant_id=%s AND id=%s", (scope.tenant_id, master_id))
        return _decode(cur.fetchone())


def find_duplicate(normalized_title: str, fingerprint: str, *, exclude_id: int | None = None) -> dict | None:
    scope = require_scope()
    sql = ("SELECT id, title FROM drama_masters WHERE tenant_id=%s "
           "AND (normalized_title=%s OR content_fingerprint=%s)")
    args: list[Any] = [scope.tenant_id, normalized_title, fingerprint]
    if exclude_id is not None:
        sql += " AND id<>%s"
        args.append(exclude_id)
    sql += " LIMIT 1"
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        return cur.fetchone()


def search_masters(query: str, catalog_type: str, page: int, page_size: int) -> dict:
    scope = require_scope()
    where = "tenant_id=%s AND catalog_type=%s"
    args: list[Any] = [scope.tenant_id, catalog_type]
    if query:
        where += " AND (title LIKE %s OR chinese_title LIKE %s)"
        args.extend((f"%{query}%", f"%{query}%"))
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS total FROM drama_masters WHERE {where}", args)
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"SELECT * FROM drama_masters WHERE {where} ORDER BY launched_at DESC, id DESC LIMIT %s OFFSET %s",
            [*args, page_size, (page - 1) * page_size],
        )
        return _page(cur.fetchall() or [], total, page, page_size)


def update_master(master_id: int, values: dict[str, Any], revision: int) -> dict | None:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE drama_masters SET catalog_type=%s, title=%s, chinese_title=%s,
               normalized_title=%s, aliases=%s, original_language=%s, launched_at=%s,
               region=%s, genres=%s, synopsis=%s, cover_url=%s,
               content_fingerprint=%s, revision=revision+1
               WHERE tenant_id=%s AND id=%s AND revision=%s""",
            (values["catalog_type"], values["title"], values["chinese_title"],
             values["normalized_title"], json.dumps(values["aliases"], ensure_ascii=False),
             values["original_language"], values["launched_at"], values["region"],
             json.dumps(values["genres"], ensure_ascii=False),
             values["synopsis"], values["cover_url"], values["content_fingerprint"],
             scope.tenant_id, master_id, revision),
        )
        changed = cur.rowcount
        conn.commit()
    return get_master(master_id) if changed else None


def delete_master(master_id: int) -> bool:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM drama_masters
               WHERE tenant_id=%s AND id=%s
                 AND NOT EXISTS (
                   SELECT 1 FROM app_application_dramas r
                   WHERE r.tenant_id=%s AND r.drama_id=drama_masters.id
                 )""",
            (scope.tenant_id, master_id, scope.tenant_id),
        )
        changed = cur.rowcount
        conn.commit()
    return changed == 1


def master_has_references(master_id: int) -> bool:
    scope = require_scope()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM app_application_dramas WHERE tenant_id=%s AND drama_id=%s LIMIT 1",
            (scope.tenant_id, master_id),
        )
        return cur.fetchone() is not None


def attach(master_id: int, values: dict[str, Any]) -> dict:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        # This scoped INSERT..SELECT is the write-time tenant ownership check.
        cur.execute(
            """INSERT INTO app_application_dramas
               (tenant_id, application_id, drama_id, display_title, status, notes, created_by)
               SELECT %s, %s, id, %s, %s, %s, %s
               FROM drama_masters WHERE tenant_id=%s AND id=%s""",
            (scope.tenant_id, scope.application_id, values["display_title"], values["status"],
             values["notes"], values["created_by"], scope.tenant_id, master_id),
        )
        changed = cur.rowcount
        conn.commit()
    if changed != 1:
        return None  # type: ignore[return-value]
    return get_reference(master_id)  # type: ignore[return-value]


def get_reference(master_id: int) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.id AS reference_id, r.application_id, r.drama_id, r.display_title,
                      r.status AS reference_status, r.notes, r.created_at AS attached_at,
                      d.catalog_type, d.title, d.chinese_title, d.aliases,
                      d.original_language, d.launched_at, d.region, d.genres,
                      d.synopsis, d.cover_url, d.revision
               FROM app_application_dramas r
               JOIN drama_masters d ON d.id=r.drama_id AND d.tenant_id=r.tenant_id
               WHERE r.tenant_id=%s AND r.application_id=%s AND r.drama_id=%s""",
            (scope.tenant_id, scope.application_id, master_id),
        )
        return _decode(cur.fetchone())


def list_references(query: str, page: int, page_size: int) -> dict:
    scope = require_scope(application=True)
    where = "r.tenant_id=%s AND r.application_id=%s"
    args: list[Any] = [scope.tenant_id, scope.application_id]
    if query:
        where += " AND (d.title LIKE %s OR r.display_title LIKE %s)"
        args.extend((f"%{query}%", f"%{query}%"))
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT COUNT(*) AS total FROM app_application_dramas r JOIN drama_masters d ON d.id=r.drama_id AND d.tenant_id=r.tenant_id WHERE {where}",
            args,
        )
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""SELECT r.id AS reference_id, r.application_id, r.drama_id, r.display_title,
                       r.status AS reference_status, r.notes, r.created_at AS attached_at,
                       d.catalog_type, d.title, d.chinese_title, d.aliases,
                       d.original_language, d.launched_at, d.region, d.genres,
                       d.synopsis, d.cover_url, d.revision
                FROM app_application_dramas r
                JOIN drama_masters d ON d.id=r.drama_id AND d.tenant_id=r.tenant_id
                WHERE {where} ORDER BY r.updated_at DESC, r.id DESC LIMIT %s OFFSET %s""",
            [*args, page_size, (page - 1) * page_size],
        )
        return _page(cur.fetchall() or [], total, page, page_size)


def update_reference(master_id: int, values: dict[str, Any]) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_application_dramas SET display_title=%s, status=%s, notes=%s
               WHERE tenant_id=%s AND application_id=%s AND drama_id=%s""",
            (values["display_title"], values["status"], values["notes"],
             scope.tenant_id, scope.application_id, master_id),
        )
        conn.commit()
    # A valid no-op update may report rowcount=0; the same fully scoped lookup
    # distinguishes it from a missing/foreign reference without leaking scope.
    return get_reference(master_id)


def detach(master_id: int) -> bool:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM app_application_dramas WHERE tenant_id=%s AND application_id=%s AND drama_id=%s",
            (scope.tenant_id, scope.application_id, master_id),
        )
        changed = cur.rowcount
        conn.commit()
    return changed == 1
