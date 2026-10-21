"""Read-only, explicitly scoped queries for readiness analytics."""
from __future__ import annotations

from typing import Any

from core.isolation import require_scope
from db import get_app_conn


def _stringify_times(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("created_at", "updated_at", "ready_at", "finished_at"):
        if result.get(field) is not None:
            result[field] = str(result[field])
    return result


def list_material_references() -> list[dict]:
    """Return the effective version for every material selected by this app."""
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.id AS reference_id, r.material_id, r.selection_mode,
                      r.selected_version_id, r.status AS reference_status,
                      r.updated_at, m.name AS material_name,
                      m.material_type, m.status AS material_status,
                      m.drama_id, d.title AS drama_title,
                      CASE WHEN r.selection_mode='latest' THEN lv.id ELSE pv.id END
                        AS effective_version_id,
                      CASE WHEN r.selection_mode='latest' THEN lv.version_number ELSE pv.version_number END
                        AS effective_version_number,
                      CASE WHEN r.selection_mode='latest' THEN lv.source_filename ELSE pv.source_filename END
                        AS effective_filename,
                      CASE WHEN r.selection_mode='latest' THEN lv.upload_status ELSE pv.upload_status END
                        AS upload_status,
                      CASE WHEN r.selection_mode='latest' THEN lv.upload_error ELSE pv.upload_error END
                        AS upload_error
                 FROM app_application_materials r
                 JOIN material_masters m
                   ON m.id=r.material_id AND m.tenant_id=r.tenant_id
                 LEFT JOIN drama_masters d
                   ON d.id=m.drama_id AND d.tenant_id=m.tenant_id
                 LEFT JOIN material_versions pv
                   ON pv.id=r.selected_version_id AND pv.tenant_id=r.tenant_id
                  AND pv.material_id=r.material_id
                 LEFT JOIN material_versions lv
                   ON lv.tenant_id=m.tenant_id AND lv.material_id=m.id
                  AND lv.version_number=m.latest_version_number
                WHERE r.tenant_id=%s AND r.application_id=%s
                ORDER BY r.updated_at DESC, r.id DESC""",
            (scope.tenant_id, scope.application_id),
        )
        return [_stringify_times(row) for row in (cur.fetchall() or [])]


def list_creative_groups() -> list[dict]:
    """Use the canonical creative-group projection so blockers stay consistent."""
    from creative_groups.repository import list_all

    return [_stringify_times(row) for row in list_all()]


def list_drafts() -> list[dict]:
    from ad_creation.repository import list_all

    return list_all()


def list_preflight_runs() -> list[dict]:
    from platform_preflight.repository import list_runs

    return list_runs()
