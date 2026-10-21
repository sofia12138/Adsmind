import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from core.isolation import Scope, bound_scope
from creative_groups import repository, service


class _Cursor:
    def __init__(self, rows=None, rowcount=1, lastrowid=51):
        self.rows = list(rows or [])
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.calls = []

    def execute(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), tuple(args or ())))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self): return self._cursor
    def begin(self): pass
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def __enter__(self): return self
    def __exit__(self, *_): return False


class CreativeGroupValidationTests(unittest.TestCase):
    def test_selection_modes_and_duplicate_materials_are_rejected(self):
        invalid = (
            {"name": "G", "materials": [{"material_id": 1, "selection_mode": "pinned"}]},
            {"name": "G", "materials": [{"material_id": 1, "selection_mode": "latest", "selected_version_id": 2}]},
            {"name": "G", "materials": [{"material_id": 1}, {"material_id": 1}]},
        )
        for values in invalid:
            with self.assertRaises(ValidationError):
                service.CreativeGroupInput(**values)

    def test_foreign_material_or_version_is_hidden_as_not_found(self):
        data = service.CreativeGroupInput(
            name="Group",
            materials=[{"material_id": 7, "selection_mode": "pinned", "selected_version_id": 9}],
        )
        with patch.object(repository, "get_selectable_material", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                service.create_group(data, "editor")
        self.assertEqual(caught.exception.status_code, 404)

    def test_non_uploaded_status_is_draft_blocker_not_a_save_error(self):
        row = {
            "reference_status": "selected", "material_status": "active",
            "effective_version_id": 9, "selected_version_upload_status": "pending_upload",
        }
        decorated = repository._row_to_item(row)
        self.assertFalse(decorated["can_deliver"])
        self.assertIn("待上传", decorated["blocking_reasons"][0])

    def test_uploaded_active_selected_item_is_deliverable(self):
        row = {
            "reference_status": "selected", "material_status": "active",
            "effective_version_id": 9, "selected_version_upload_status": "uploaded",
        }
        decorated = repository._row_to_item(row)
        self.assertTrue(decorated["can_deliver"])
        self.assertEqual(decorated["blocking_reasons"], [])


class CreativeGroupRepositoryScopeTests(unittest.TestCase):
    def test_selectable_material_filters_tenant_and_application(self):
        cursor = _Cursor([{"material_id": 7, "selected_version_id": 9}])
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(cursor)):
            repository.get_selectable_material(7, 9)
        sql, args = cursor.calls[0]
        self.assertIn("r.tenant_id=%s AND r.application_id=%s AND r.material_id=%s", sql)
        self.assertIn("r.status='selected' AND m.status='active'", sql)
        self.assertIn("v.tenant_id=r.tenant_id AND v.material_id=r.material_id", sql)
        self.assertEqual(args, (9, 41, 8, 7, 9))

    def test_get_and_delete_filter_both_ownership_levels(self):
        get_cursor = _Cursor([])
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(get_cursor)):
            self.assertIsNone(repository.get(99))
        self.assertEqual(get_cursor.calls[0][1], (41, 8, 99))

        delete_cursor = _Cursor(rowcount=1)
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(delete_cursor)):
            self.assertTrue(repository.delete(99))
        self.assertEqual(delete_cursor.calls[0][1], (41, 8, 99))

    def test_0007_is_reversible_and_has_scoped_foreign_keys(self):
        from migrations.versions import v0007_creative_groups as migration
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertTrue(migration.REVERSIBLE)
        self.assertIn("FOREIGN KEY (tenant_id, application_id, material_id)", source)
        self.assertIn("FOREIGN KEY (selected_version_id, tenant_id, material_id)", source)
        self.assertLess(source.index("DROP TABLE app_creative_group_materials"), source.index("DROP INDEX uq_creative_group_scope_id"))


if __name__ == "__main__":
    unittest.main()
