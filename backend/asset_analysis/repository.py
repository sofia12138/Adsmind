"""Scoped source readers for material/drama analysis.

The analysis deliberately reads APP and BIZ separately.  Cross-database joins
would make the verified tenant/application boundary hard to audit.
"""
from __future__ import annotations

import json
from typing import Any

from core.isolation import account_clause, require_scope
from db import get_app_conn, get_biz_conn


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value if value is not None else fallback


def list_materials() -> list[dict]:
    """Application-selected materials and their effective versions."""
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.material_id, r.status AS reference_status, r.selection_mode,
                      r.selected_version_id, r.updated_at AS reference_updated_at,
                      m.name, m.material_type, m.status AS material_status,
                      m.drama_id, d.title AS drama_title,
                      CASE WHEN r.selection_mode='latest' THEN lv.id ELSE pv.id END AS version_id,
                      CASE WHEN r.selection_mode='latest' THEN lv.version_number ELSE pv.version_number END AS version_number,
                      CASE WHEN r.selection_mode='latest' THEN lv.source_filename ELSE pv.source_filename END AS source_filename,
                      CASE WHEN r.selection_mode='latest' THEN lv.upload_status ELSE pv.upload_status END AS upload_status,
                      CASE WHEN r.selection_mode='latest' THEN lv.created_at ELSE pv.created_at END AS version_created_at
                 FROM app_application_materials r
                 JOIN material_masters m ON m.id=r.material_id AND m.tenant_id=r.tenant_id
                 LEFT JOIN drama_masters d ON d.id=m.drama_id AND d.tenant_id=m.tenant_id
                 LEFT JOIN material_versions pv
                   ON pv.id=r.selected_version_id AND pv.tenant_id=r.tenant_id AND pv.material_id=r.material_id
                 LEFT JOIN material_versions lv
                   ON lv.tenant_id=m.tenant_id AND lv.material_id=m.id
                  AND lv.version_number=m.latest_version_number
                WHERE r.tenant_id=%s AND r.application_id=%s
                ORDER BY r.material_id""",
            (scope.tenant_id, scope.application_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]


def list_material_mappings() -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, platform, account_id, material_id, version_id,
                      platform_asset_id, upload_status, updated_at
                 FROM app_platform_material_mappings
                WHERE tenant_id=%s AND application_id=%s
                ORDER BY material_id, version_id, platform, account_id""",
            (scope.tenant_id, scope.application_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]


def list_accounts() -> list[dict]:
    scope = require_scope(application=True)
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT platform, account_id, account_name, currency, timezone, status, updated_at
                 FROM biz_ad_accounts
                WHERE tenant_id=%s AND application_id=%s
                ORDER BY platform, account_id""",
            (scope.tenant_id, scope.application_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]


def list_creative_groups() -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT gm.material_id, g.id AS creative_group_id, g.name AS creative_group_name,
                      'active' AS creative_group_status
                 FROM app_creative_group_materials gm
                 JOIN app_creative_groups g
                   ON g.id=gm.creative_group_id AND g.tenant_id=gm.tenant_id
                  AND g.application_id=gm.application_id
                WHERE gm.tenant_id=%s AND gm.application_id=%s
                ORDER BY gm.material_id, g.id""",
            (scope.tenant_id, scope.application_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]


def list_draft_snapshots() -> list[dict]:
    scope = require_scope(application=True)
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, title, status, creative_group_id, creative_snapshot,
                      execution_snapshot, updated_at
                 FROM app_ad_creation_drafts
                WHERE tenant_id=%s AND application_id=%s
                ORDER BY updated_at DESC, id DESC""",
            (scope.tenant_id, scope.application_id),
        )
        rows = []
        for raw in cur.fetchall() or []:
            row = dict(raw)
            row["creative_snapshot"] = _json(row.get("creative_snapshot"), {})
            row["execution_snapshot"] = _json(row.get("execution_snapshot"), None)
            rows.append(row)
        return rows


def list_facts(date_from: str, date_to: str, *, platform: str | None = None,
               account_id: str | None = None) -> list[dict]:
    """Read attribution facts only for accounts owned by the verified app.

    This source documents spend and attributed recharge in USD.  We do not
    combine it with the legacy normalized report because that table cannot
    distinguish absent revenue from a real zero.
    """
    clauses = [account_clause(), "ds_account_local BETWEEN %s AND %s"]
    params: list[Any] = [date_from, date_to]
    if platform:
        clauses.append("platform=%s")
        params.append(platform)
    if account_id:
        clauses.append("account_id=%s")
        params.append(account_id)
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT ds_account_local AS stat_date, platform, account_id,
                       account_timezone, ad_id, ad_name, creative_id, video_id,
                       spend, impressions, clicks, install AS installs,
                       conversion AS conversions, total_recharge_amount AS revenue,
                       synced_at, upstream_updated_at
                  FROM biz_attribution_ad_daily
                 WHERE {' AND '.join(clauses)}
                 ORDER BY ds_account_local, platform, account_id, ad_id""",
            params,
        )
        return [dict(row) for row in (cur.fetchall() or [])]
