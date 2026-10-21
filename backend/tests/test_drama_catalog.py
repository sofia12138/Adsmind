import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from core.isolation import Scope, bound_scope
from drama_catalog import repository, service


class _Cursor:
    def __init__(self, rows=None, rowcount=1, lastrowid=91):
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

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ValidationTests(unittest.TestCase):
    def test_master_normalizes_lists_and_rejects_unsafe_cover(self):
        row = service.MasterInput(
            title="  My   Drama ", aliases=["Alias", " alias ", "别名"], genres=["Romance", "Romance"]
        )
        self.assertEqual(row.title, "My Drama")
        self.assertEqual(row.aliases, ["Alias", "别名"])
        self.assertEqual(row.genres, ["Romance"])
        with self.assertRaises(ValidationError):
            service.MasterInput(title="Drama", cover_url="https://user:secret@example.com/cover.jpg")

    def test_update_requires_revision_and_reference_status_is_bounded(self):
        with self.assertRaises(ValidationError):
            service.MasterUpdate(title="Drama")
        with self.assertRaises(ValidationError):
            service.ReferenceInput(drama_id=1, status="deleted")

    def test_cross_tenant_master_is_a_not_found_during_attach(self):
        with patch.object(repository, "get_master", return_value=None), self.assertRaises(HTTPException) as error:
            service.attach(service.ReferenceInput(drama_id=7), "user")
        self.assertEqual(error.exception.status_code, 404)

    def test_detach_only_removes_application_reference(self):
        with patch.object(repository, "detach", return_value=True) as detach, patch.object(repository, "delete_master") as delete:
            service.detach(7)
        detach.assert_called_once_with(7)
        delete.assert_not_called()


class RepositoryScopeTests(unittest.TestCase):
    def test_master_lookup_always_filters_tenant(self):
        cursor = _Cursor([{"id": 7, "tenant_id": 41, "title": "Scoped", "aliases": "[]", "genres": "[]"}])
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(cursor)):
            row = repository.get_master(7)
        self.assertEqual(row["title"], "Scoped")
        sql, args = cursor.calls[0]
        self.assertIn("WHERE tenant_id=%s AND id=%s", sql)
        self.assertEqual(args, (41, 7))

    def test_attach_checks_master_tenant_inside_the_insert(self):
        insert = _Cursor(rowcount=1)
        reference = {"drama_id": 7, "title": "Scoped", "aliases": "[]", "genres": "[]"}
        read = _Cursor([reference])
        connections = iter((_Connection(insert), _Connection(read)))
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", side_effect=lambda: next(connections)):
            row = repository.attach(7, {
                "display_title": "", "status": "active", "notes": "", "created_by": "user",
            })
        self.assertEqual(row["drama_id"], 7)
        sql, args = insert.calls[0]
        self.assertIn("INSERT INTO app_application_dramas", sql)
        self.assertIn("FROM drama_masters WHERE tenant_id=%s AND id=%s", sql)
        self.assertEqual(args, (41, 8, "", "active", "", "user", 41, 7))
        read_sql, read_args = read.calls[0]
        self.assertIn("r.tenant_id=%s AND r.application_id=%s", read_sql)
        self.assertEqual(read_args, (41, 8, 7))

    def test_reference_update_and_detach_filter_both_scopes(self):
        for operation in ("update", "detach"):
            cursor = _Cursor(rowcount=1)
            connections = [_Connection(cursor)]
            if operation == "update":
                connections.append(_Connection(_Cursor([{"drama_id": 7, "aliases": "[]", "genres": "[]"}])))
            with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", side_effect=connections):
                if operation == "update":
                    repository.update_reference(7, {"display_title": "D", "status": "paused", "notes": "N"})
                else:
                    repository.detach(7)
            sql, args = cursor.calls[0]
            self.assertIn("tenant_id=%s AND application_id=%s AND drama_id=%s", sql)
            self.assertEqual(args[-3:], (41, 8, 7))

    def test_migration_has_scoped_unique_keys_and_reversible_order(self):
        from migrations.versions import v0004_drama_catalog as migration
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertTrue(migration.REVERSIBLE)
        self.assertIn("UNIQUE KEY uq_drama_master_title (tenant_id, normalized_title)", source)
        self.assertIn("UNIQUE KEY uq_application_drama (tenant_id, application_id, drama_id)", source)
        self.assertIn("FOREIGN KEY (drama_id, tenant_id)", source)
        self.assertLess(source.index('DROP TABLE app_application_dramas'), source.index('DROP TABLE drama_masters'))


if __name__ == "__main__":
    unittest.main()
