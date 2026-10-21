"""Readiness analytics classification, filtering and scope coverage."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.isolation import Scope, bound_scope
from readiness_analytics import repository, service
from readiness_analytics.routes import router


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), tuple(args or ())))

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor): self._cursor = cursor
    def cursor(self): return self._cursor
    def __enter__(self): return self
    def __exit__(self, *_): return False


def fixture():
    materials = [
        {"reference_id": 1, "material_id": 10, "material_name": "Uploaded", "reference_status": "selected",
         "material_status": "active", "effective_version_id": 101, "upload_status": "uploaded", "updated_at": "2026-10-20 10:00:00"},
        {"reference_id": 2, "material_id": 20, "material_name": "No version", "reference_status": "selected",
         "material_status": "active", "effective_version_id": None, "upload_status": None, "updated_at": "2026-10-20 11:00:00"},
        {"reference_id": 3, "material_id": 30, "material_name": "Odd status", "reference_status": "selected",
         "material_status": "active", "effective_version_id": 303, "upload_status": "mystery", "updated_at": "2026-10-20 12:00:00"},
    ]
    creatives = [
        {"id": 40, "name": "Ready group", "can_deliver": True, "blocking_reasons": [], "materials": [{}], "updated_at": "2026-10-20 13:00:00"},
        {"id": 41, "name": "Blocked group", "can_deliver": False, "blocking_reasons": ["素材等待上传"], "materials": [{}], "updated_at": "2026-10-20 14:00:00"},
    ]
    drafts = [
        {"id": "ready-no-run", "title": "Ready no run", "status": "READY", "revision": 2, "blocking_reasons": [], "ready_at": "2026-10-20 15:00:00", "updated_at": "2026-10-20 15:00:00"},
        {"id": "blocked", "title": "Blocked draft", "status": "DRAFT", "revision": 1, "blocking_reasons": [{"code": "account_inactive", "message": "账户停用"}], "updated_at": "2026-10-20 16:00:00"},
        {"id": "pending", "title": "Pending draft", "status": "DRAFT", "revision": 1, "blocking_reasons": [], "updated_at": "2026-10-20 17:00:00"},
    ]
    runs = [
        {"id": "run-blocked", "draft_id": "blocked", "status": "BLOCKED", "blocking_reasons": [
            {"code": "credential_missing", "message": "凭证缺失"},
            {"code": "credential_missing", "message": "另一个账户凭证缺失"},
        ], "dry_run": True, "external_write_authorized": False, "finished_at": "2026-10-20 18:00:00"},
    ]
    return materials, creatives, drafts, runs


class ReadinessAnalyticsTests(unittest.TestCase):
    def test_public_contract_exposes_get_only_routes(self):
        paths = {route.path: route.methods for route in router.routes}
        self.assertEqual(paths["/readiness-analytics/overview"], {"GET"})
        self.assertEqual(paths["/readiness-analytics/details"], {"GET"})

    def _snapshot(self):
        materials, creatives, drafts, runs = fixture()
        with (
            bound_scope(Scope(11, 22)),
            patch.object(repository, "list_material_references", return_value=materials),
            patch.object(repository, "list_creative_groups", return_value=creatives),
            patch.object(repository, "list_drafts", return_value=drafts),
            patch.object(repository, "list_preflight_runs", return_value=runs),
        ):
            return service.build_snapshot()

    def test_missing_unknown_pending_and_not_run_are_not_counted_as_success(self):
        result = self._snapshot()
        self.assertEqual(result["summary"]["materials"]["uploaded"], 1)
        self.assertEqual(result["summary"]["materials"]["missing"], 1)
        self.assertEqual(result["summary"]["materials"]["unknown"], 1)
        self.assertEqual(result["summary"]["drafts"], {"ready": 1, "blocked": 1, "pending": 1, "unknown": 0})
        self.assertEqual(result["summary"]["preflights"]["not_run"], 1)
        self.assertEqual(result["summary"]["preflight_blocking_reasons"], [{"code": "credential_missing", "count": 2}])
        self.assertTrue(result["read_only"])
        self.assertIn("不是广告效果", result["disclaimer"])

    def test_details_filter_reason_search_and_pagination(self):
        materials, creatives, drafts, runs = fixture()
        with (
            bound_scope(Scope(11, 22)),
            patch.object(repository, "list_material_references", return_value=materials),
            patch.object(repository, "list_creative_groups", return_value=creatives),
            patch.object(repository, "list_drafts", return_value=drafts),
            patch.object(repository, "list_preflight_runs", return_value=runs),
        ):
            result = service.details(service.DetailFilters(
                entity_type="preflight", status="blocked", reason_code="credential_missing",
                query="Blocked draft", page=1, page_size=1,
            ))
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["entity_id"], "run-blocked")

    def test_material_query_uses_both_verified_scope_ids(self):
        cursor = _Cursor([])
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(cursor)):
            repository.list_material_references()
        sql, args = cursor.calls[0]
        self.assertIn("r.tenant_id=%s AND r.application_id=%s", sql)
        self.assertEqual(args, (41, 8))


if __name__ == "__main__":
    unittest.main()
