import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from pymysql.err import IntegrityError

from core.isolation import Scope, bound_scope
from material_catalog import repository, service


class _Cursor:
    def __init__(self, rows=None, rowcount=1, lastrowid=71):
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


class ValidationTests(unittest.TestCase):
    def test_version_rejects_path_empty_file_and_invalid_hash(self):
        for values in (
            {"source_filename": "../clip.mp4", "mime_type": "video/mp4", "size_bytes": 1},
            {"source_filename": "clip.mp4", "mime_type": "video/mp4", "size_bytes": 0},
            {"source_filename": "clip.mp4", "mime_type": "video/mp4", "size_bytes": 1, "checksum_sha256": "no"},
        ):
            with self.assertRaises(ValidationError): service.VersionInput(**values)

    def test_selection_mode_contract(self):
        with self.assertRaises(ValidationError):
            service.ReferenceInput(material_id=1, selection_mode="pinned")
        with self.assertRaises(ValidationError):
            service.ReferenceInput(material_id=1, selection_mode="latest", selected_version_id=9)

    def test_cross_tenant_drama_is_hidden_as_not_found(self):
        with patch.object(repository, "get_drama", return_value=None), self.assertRaises(HTTPException) as error:
            service.create_master(service.MasterInput(name="Clip", material_type="video", drama_id=8), "u")
        self.assertEqual(error.exception.status_code, 404)

    def test_unconfigured_storage_never_reports_upload_success(self):
        version = {
            "id": 9, "tenant_id": 4, "material_id": 7, "version_number": 1,
            "source_filename": "clip.mp4", "upload_status": "pending_upload",
        }
        with patch.object(repository, "create_version", return_value=version):
            row = service.register_version(7, service.VersionInput(source_filename="clip.mp4", mime_type="video/mp4", size_bytes=42), "u")
        self.assertEqual(row["upload_status"], "pending_upload")
        self.assertFalse(row["upload"]["available"])
        self.assertIsNone(row["upload"]["upload_url"])

    def test_detach_reports_creative_group_reference_as_a_conflict(self):
        with patch.object(repository, "detach", side_effect=IntegrityError(1451, "foreign key")):
            with self.assertRaises(HTTPException) as error:
                service.detach(7)
        self.assertEqual(error.exception.status_code, 409)


class RepositoryScopeTests(unittest.TestCase):
    def test_master_and_version_reads_filter_tenant(self):
        for call, expected in (
            (lambda: repository.get_master(7), (41, 7)),
            (lambda: repository.get_version(7, 9), (41, 7, 9)),
        ):
            cursor = _Cursor([{"id": 7, "tags": "[]", "metadata_json": "{}"}])
            with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=_Connection(cursor)):
                call()
            self.assertIn("tenant_id=%s", cursor.calls[0][0])
            self.assertEqual(cursor.calls[0][1], expected)

    def test_attach_checks_material_and_version_inside_scoped_insert(self):
        insert = _Cursor(rowcount=1)
        read = _Cursor([{"material_id": 7}])
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", side_effect=[_Connection(insert), _Connection(read)]):
            row = repository.attach(7, {"selected_version_id": 9, "selection_mode": "pinned", "status": "selected", "notes": "", "created_by": "u"})
        self.assertEqual(row["material_id"], 7)
        sql, args = insert.calls[0]
        self.assertIn("m.tenant_id=%s AND m.id=%s", sql)
        self.assertIn("v.tenant_id=m.tenant_id AND v.material_id=m.id", sql)
        self.assertEqual(args, (41, 8, "pinned", "selected", "", "u", 9, 41, 7, 9))
        read_sql, read_args = read.calls[0]
        self.assertIn("r.tenant_id=%s AND r.application_id=%s AND r.material_id=%s", read_sql)
        self.assertEqual(read_args, (41, 8, 7))

    def test_update_and_detach_reference_filter_tenant_and_application(self):
        for operation in ("update", "detach"):
            write = _Cursor(rowcount=1)
            connections = [_Connection(write)]
            if operation == "update": connections.append(_Connection(_Cursor([{"material_id": 7}])))
            with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", side_effect=connections):
                if operation == "update":
                    repository.update_reference(7, {"selected_version_id": None, "selection_mode": "latest", "status": "paused", "notes": "n"})
                else:
                    repository.detach(7)
            sql, args = write.calls[0]
            self.assertIn("tenant_id=%s AND", sql)
            self.assertIn("application_id=%s AND", sql)
            self.assertIn("material_id=%s", sql)
            self.assertIn((41, 8, 7), tuple(args[i:i + 3] for i in range(len(args) - 2)))

    def test_version_number_is_allocated_under_lock(self):
        write = _Cursor([{"latest_version_number": 2}], lastrowid=90)
        read = _Cursor([{"id": 90, "tenant_id": 41, "material_id": 7, "metadata_json": "{}"}])
        values = {"source_filename": "a.mp4", "file_extension": "mp4", "mime_type": "video/mp4", "size_bytes": 1,
                  "checksum_sha256": None, "width": None, "height": None, "duration_ms": None, "metadata_json": {}, "notes": "", "created_by": "u"}
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", side_effect=[_Connection(write), _Connection(read)]):
            repository.create_version(7, values)
        self.assertIn("FOR UPDATE", write.calls[0][0])
        self.assertEqual(write.calls[1][1][2], 3)

    def test_migration_is_reversible_and_scoped(self):
        from migrations.versions import v0006_material_catalog as migration
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertTrue(migration.REVERSIBLE)
        self.assertIn("FOREIGN KEY (application_id, tenant_id)", source)
        self.assertIn("FOREIGN KEY (selected_version_id, tenant_id, material_id)", source)
        self.assertLess(source.index('DROP TABLE app_application_materials'), source.index('DROP TABLE material_versions'))
        self.assertLess(source.index('DROP TABLE material_versions'), source.index('DROP TABLE material_masters'))

    def test_release_schema_guard_requires_material_tables(self):
        from migrations.schema_guard import APP_RESOURCE_REQUIREMENTS
        self.assertEqual(
            {"material_masters", "material_versions", "app_application_materials"},
            {name for name in APP_RESOURCE_REQUIREMENTS if name in {
                "material_masters", "material_versions", "app_application_materials"
            }},
        )


if __name__ == "__main__": unittest.main()
