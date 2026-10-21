"""Material/drama analytics semantics and isolation contract."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

from asset_analysis import repository, service
from asset_analysis.routes import router
from core.isolation import Scope, bound_scope


MATERIALS = [
    {"material_id": 1, "name": "Mapped", "drama_id": 10, "drama_title": "Drama A", "version_id": 101,
     "version_number": 1, "source_filename": "mapped.mp4", "upload_status": "uploaded"},
    {"material_id": 2, "name": "Unmapped", "drama_id": 10, "drama_title": "Drama A", "version_id": 201,
     "version_number": 1, "source_filename": "unmapped.mp4", "upload_status": "uploaded"},
    {"material_id": 3, "name": "Not uploaded", "drama_id": None, "drama_title": None, "version_id": 301,
     "version_number": 1, "source_filename": "pending.mp4", "upload_status": "pending_upload"},
    {"material_id": 4, "name": "No version", "drama_id": None, "drama_title": None, "version_id": None,
     "version_number": None, "source_filename": None, "upload_status": None},
]
MAPPINGS = [
    {"id": 501, "platform": "tiktok", "account_id": "acc-1", "material_id": 1, "version_id": 101,
     "platform_asset_id": "video-1", "upload_status": "uploaded"},
    {"id": 502, "platform": "tiktok", "account_id": "acc-1", "material_id": 3, "version_id": 301,
     "platform_asset_id": "video-3", "upload_status": "pending_upload"},
]
ACCOUNTS = [{"platform": "tiktok", "account_id": "acc-1", "account_name": "A", "currency": "USD", "timezone": "Asia/Shanghai"}]
FACTS = [
    {"stat_date": dt.date(2026, 10, 20), "platform": "tiktok", "account_id": "acc-1",
     "account_timezone": "Asia/Shanghai", "ad_id": "ad-1", "ad_name": "Ad", "creative_id": "", "video_id": "video-1",
     "spend": "10.0000", "revenue": "20.0000", "impressions": 100, "clicks": 10, "installs": 2,
     "conversions": 1, "synced_at": "2026-10-21 01:00:00", "upstream_updated_at": "2026-10-21 00:00:00"},
    {"stat_date": dt.date(2026, 10, 20), "platform": "tiktok", "account_id": "acc-1",
     "account_timezone": "Asia/Shanghai", "ad_id": "ad-x", "ad_name": "Unknown", "creative_id": "", "video_id": "unknown",
     "spend": "7.0000", "revenue": "0.0000", "impressions": 50, "clicks": 1, "installs": 0,
     "conversions": 0, "synced_at": "2026-10-21 01:00:00", "upstream_updated_at": None},
]


class _Cursor:
    def __init__(self): self.calls = []
    def execute(self, sql, args=None): self.calls.append((" ".join(sql.split()), tuple(args or ())))
    def fetchall(self): return []


class _Connection:
    def __init__(self, cursor): self._cursor = cursor
    def cursor(self): return self._cursor
    def __enter__(self): return self
    def __exit__(self, *_): return False


class AssetAnalysisTests(unittest.TestCase):
    def _report(self, dimension="material"):
        with (
            bound_scope(Scope(7, 9)),
            patch.object(repository, "list_materials", return_value=MATERIALS),
            patch.object(repository, "list_material_mappings", return_value=MAPPINGS),
            patch.object(repository, "list_accounts", return_value=ACCOUNTS),
            patch.object(repository, "list_creative_groups", return_value=[]),
            patch.object(repository, "list_draft_snapshots", return_value=[]),
            patch.object(repository, "list_facts", return_value=FACTS),
        ):
            return service.report(service.AnalysisFilters(
                dimension=dimension, date_from=dt.date(2026, 10, 20), date_to=dt.date(2026, 10, 20)))

    def test_routes_are_get_only(self):
        self.assertEqual({route.path: route.methods for route in router.routes}, {"/asset-analysis/report": {"GET"}})

    def test_material_states_and_roi_are_conservative(self):
        result = self._report()
        rows = {row["entity_id"]: row for row in result["items"]}
        self.assertEqual(rows["1"]["coverage_status"], "complete")
        self.assertEqual(rows["1"]["metrics"]["roi"], "2.000000")
        self.assertEqual(rows["2"]["coverage_status"], "unmapped")
        self.assertIsNone(rows["2"]["metrics"]["roi"])
        self.assertIsNone(rows["2"]["metrics"]["spend"])
        self.assertEqual(rows["3"]["coverage_status"], "not_uploaded")
        self.assertIsNone(rows["3"]["metrics"]["roi"])
        self.assertEqual(rows["4"]["coverage_status"], "missing_version")
        self.assertIsNone(rows["4"]["metrics"]["revenue_attributed"])
        self.assertEqual(result["coverage"]["unmapped_fact_rows"], 1)
        self.assertTrue(result["read_only"])

    def test_drama_rollup_withholds_roi_when_any_material_is_incomplete(self):
        result = self._report("drama")
        drama = next(row for row in result["items"] if row["entity_id"] == "10")
        self.assertEqual(drama["coverage_status"], "partial")
        self.assertIsNone(drama["metrics"]["roi"])
        self.assertEqual(drama["material_count"], 2)

    def test_date_range_validation(self):
        with self.assertRaises(ValueError):
            service.AnalysisFilters(date_from=dt.date(2026, 10, 21), date_to=dt.date(2026, 10, 20))

    def test_material_reader_uses_both_scope_ids(self):
        cursor = _Cursor()
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(cursor)):
            repository.list_materials()
        sql, args = cursor.calls[0]
        self.assertIn("r.tenant_id=%s AND r.application_id=%s", sql)
        self.assertEqual(args, (41, 8))

    def test_fact_reader_applies_verified_account_clause(self):
        cursor = _Cursor()
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_biz_conn", return_value=_Connection(cursor)):
            repository.list_facts("2026-10-20", "2026-10-20")
        sql, args = cursor.calls[0]
        self.assertIn("tenant_id = 41", sql)
        self.assertIn("application_id = 8", sql)
        self.assertEqual(args, ("2026-10-20", "2026-10-20"))


if __name__ == "__main__":
    unittest.main()
