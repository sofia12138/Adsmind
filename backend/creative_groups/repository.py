"""Scoped persistence for material-backed creative groups."""
from __future__ import annotations

import json
from typing import Any

from core.isolation import require_scope
from db import get_app_conn


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_item(row: dict) -> dict:
    result = dict(row)
    status = result.get("selected_version_upload_status")
    reasons: list[str] = []
    if result.get("reference_status") != "selected":
        reasons.append("素材在当前应用中已暂停")
    if result.get("material_status") != "active":
        reasons.append("素材主档已归档")
    if result.get("effective_version_id") is None:
        reasons.append("素材尚未登记版本")
    elif status != "uploaded":
        labels = {
            "pending_upload": "所选版本仍在待上传状态",
            "failed": "所选版本上传失败",
        }
        reasons.append(labels.get(status, "所选版本尚未上传完成"))
    result["blocking_reasons"] = reasons
    result["can_deliver"] = not reasons
    return result


_ITEM_SELECT = """
    SELECT i.material_id, i.selection_mode, i.selected_version_id, i.position,
           m.name AS material_name, m.material_type, m.status AS material_status,
           r.status AS reference_status,
           CASE WHEN i.selection_mode='latest' THEN lv.id ELSE pv.id END
             AS effective_version_id,
           CASE WHEN i.selection_mode='latest' THEN lv.version_number ELSE pv.version_number END
             AS selected_version_number,
           CASE WHEN i.selection_mode='latest' THEN lv.upload_status ELSE pv.upload_status END
             AS selected_version_upload_status,
           CASE WHEN i.selection_mode='latest' THEN lv.source_filename ELSE pv.source_filename END
             AS selected_version_filename
      FROM app_creative_group_materials i
      JOIN material_masters m
        ON m.id=i.material_id AND m.tenant_id=i.tenant_id
      JOIN app_application_materials r
        ON r.tenant_id=i.tenant_id AND r.application_id=i.application_id
       AND r.material_id=i.material_id
      LEFT JOIN material_versions pv
        ON pv.id=i.selected_version_id AND pv.tenant_id=i.tenant_id
       AND pv.material_id=i.material_id
      LEFT JOIN material_versions lv
        ON lv.tenant_id=m.tenant_id AND lv.material_id=m.id
       AND lv.version_number=m.latest_version_number
"""


def _items(conn, group_id: int) -> list[dict]:
    scope = require_scope(application=True)
    cur = conn.cursor()
    cur.execute(
        _ITEM_SELECT + """
         WHERE i.tenant_id=%s AND i.application_id=%s AND i.creative_group_id=%s
         ORDER BY i.position, i.id""",
        (scope.tenant_id, scope.application_id, group_id),
    )
    return [_row_to_item(row) for row in (cur.fetchall() or [])]


def _decorate(row: dict, items: list[dict]) -> dict:
    result = dict(row)
    result["asset_refs"] = _decode_json(result.get("asset_refs")) or []
    result["materials"] = items
    reasons = [reason for item in items for reason in item["blocking_reasons"]]
    if not items:
        reasons.append("创意组没有可用素材")
    result["blocking_reasons"] = list(dict.fromkeys(reasons))
    result["can_deliver"] = bool(items) and not reasons
    return result


def get_selectable_material(material_id: int, selected_version_id: int | None) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.material_id, r.status AS reference_status, m.status AS material_status,
                      v.id AS selected_version_id
                 FROM app_application_materials r
                 JOIN material_masters m
                   ON m.id=r.material_id AND m.tenant_id=r.tenant_id
                 LEFT JOIN material_versions v
                   ON v.id=%s AND v.tenant_id=r.tenant_id AND v.material_id=r.material_id
                WHERE r.tenant_id=%s AND r.application_id=%s AND r.material_id=%s
                  AND r.status='selected' AND m.status='active'
                  AND (%s IS NULL OR v.id IS NOT NULL)""",
            (selected_version_id, scope.tenant_id, scope.application_id, material_id, selected_version_id),
        )
        return cur.fetchone()


def create(name: str, materials: list[dict], created_by: str) -> dict:
    scope = require_scope(application=True)
    payload = json.dumps(materials, ensure_ascii=False)
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO app_creative_groups
                   (tenant_id, application_id, name, asset_refs, created_by)
                   VALUES (%s,%s,%s,%s,%s)""",
                (scope.tenant_id, scope.application_id, name, payload, created_by),
            )
            group_id = cur.lastrowid
            _replace_items(cur, scope.tenant_id, scope.application_id, group_id, materials)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get(group_id)  # type: ignore[return-value]


def get(group_id: int) -> dict | None:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM app_creative_groups
               WHERE tenant_id=%s AND application_id=%s AND id=%s""",
            (scope.tenant_id, scope.application_id, group_id),
        )
        row = cur.fetchone()
        return _decorate(row, _items(conn, group_id)) if row else None


def list_all() -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM app_creative_groups
               WHERE tenant_id=%s AND application_id=%s
               ORDER BY updated_at DESC, id DESC""",
            (scope.tenant_id, scope.application_id),
        )
        rows = cur.fetchall() or []
        return [_decorate(row, _items(conn, int(row["id"]))) for row in rows]


def _replace_items(cur, tenant_id: int, application_id: int, group_id: int, materials: list[dict]) -> None:
    for position, item in enumerate(materials):
        cur.execute(
            """INSERT INTO app_creative_group_materials
               (tenant_id, application_id, creative_group_id, material_id,
                selection_mode, selected_version_id, position)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (tenant_id, application_id, group_id, item["material_id"],
             item["selection_mode"], item["selected_version_id"], position),
        )


def update(group_id: int, name: str, materials: list[dict]) -> dict | None:
    scope = require_scope(application=True)
    payload = json.dumps(materials, ensure_ascii=False)
    with get_app_conn() as conn:
        conn.begin()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE app_creative_groups SET name=%s, asset_refs=%s
                   WHERE tenant_id=%s AND application_id=%s AND id=%s""",
                (name, payload, scope.tenant_id, scope.application_id, group_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    """SELECT id FROM app_creative_groups
                       WHERE tenant_id=%s AND application_id=%s AND id=%s""",
                    (scope.tenant_id, scope.application_id, group_id),
                )
                if not cur.fetchone():
                    conn.rollback()
                    return None
            cur.execute(
                """DELETE FROM app_creative_group_materials
                   WHERE tenant_id=%s AND application_id=%s AND creative_group_id=%s""",
                (scope.tenant_id, scope.application_id, group_id),
            )
            _replace_items(cur, scope.tenant_id, scope.application_id, group_id, materials)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get(group_id)


def delete(group_id: int) -> bool:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM app_creative_groups
               WHERE tenant_id=%s AND application_id=%s AND id=%s""",
            (scope.tenant_id, scope.application_id, group_id),
        )
        changed = cur.rowcount
        conn.commit()
        return changed == 1
