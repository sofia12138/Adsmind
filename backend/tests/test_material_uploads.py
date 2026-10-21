import hashlib
import io
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from auth import User
from core.isolation import Scope, bound_scope
from material_catalog.routes import writer
from material_uploads import service
from material_uploads.storage import LocalStorage, StoredObject


class LocalStorageTests(unittest.TestCase):
    def test_direct_and_multipart_bytes_are_private_scoped_and_hashable(self):
        data = b"\x89PNG\r\n\x1a\n" + b"verified-content"
        with tempfile.TemporaryDirectory() as root:
            store = LocalStorage(root)
            key = store.object_key(tenant_id=4, application_id=8, material_id=12, version_id=16, upload_id="safe-id", extension="png")
            self.assertTrue(key.startswith("tenants/4/applications/8/"))
            store.write_part(key, 1, io.BytesIO(data[:10]))
            store.write_part(key, 2, io.BytesIO(data[10:]))
            store.assemble(key, 2)
            actual = store.inspect(key, "image.png")
            self.assertEqual(actual.size_bytes, len(data))
            self.assertEqual(actual.checksum_sha256, hashlib.sha256(data).hexdigest())
            self.assertEqual(actual.detected_mime_type, "image/png")

    def test_object_key_cannot_escape_storage_root(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalStorage(root)
            with self.assertRaises(ValueError):
                store.write_direct("../escape", io.BytesIO(b"no"))
            self.assertFalse((Path(root).parent / "escape").exists())


class UploadServiceTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "upload-1", "tenant_id": 41, "application_id": 8,
            "material_id": 7, "version_id": 9, "idempotency_key": "request-123",
            "upload_mode": "direct", "status": "uploading", "storage_backend": "local",
            "storage_key": "private/key.mp4", "expected_size_bytes": 12,
            "expected_mime_type": "video/mp4", "expected_checksum_sha256": "a" * 64,
            "received_size_bytes": 12, "expires_at": datetime.now() + timedelta(minutes=10),
        }

    def test_completion_is_idempotent_after_verified_upload(self):
        uploaded = {**self.row, "status": "uploaded", "completed_at": datetime.now()}
        with bound_scope(Scope(41, 8)), patch("material_uploads.service.repository.get_upload", return_value=uploaded), patch("material_uploads.service.get_storage") as storage:
            result = service.complete("upload-1", service.CompleteInput(idempotency_key="request-123"), "user")
        self.assertEqual(result["status"], "uploaded")
        storage.assert_not_called()

    def test_version_is_not_marked_uploaded_when_checksum_fails(self):
        fake_store = unittest.mock.Mock()
        fake_store.inspect.return_value = StoredObject(12, "b" * 64, "video/mp4")
        with bound_scope(Scope(41, 8)), \
             patch("material_uploads.service.repository.get_upload", return_value=self.row), \
             patch("material_uploads.service.repository.get_version_for_upload", return_value={"source_filename": "clip.mp4"}), \
             patch("material_uploads.service.repository.mark_failed") as failed, \
             patch("material_uploads.service.repository.finalize") as finalize, \
             patch("material_uploads.service.get_storage", return_value=fake_store), \
             self.assertRaises(HTTPException) as error:
            service.complete("upload-1", service.CompleteInput(idempotency_key="request-123"), "user")
        self.assertEqual(error.exception.status_code, 422)
        failed.assert_called_once()
        finalize.assert_not_called()

    def test_verified_file_is_the_only_path_to_finalize(self):
        fake_store = unittest.mock.Mock()
        fake_store.inspect.return_value = StoredObject(12, "a" * 64, "video/mp4")
        uploaded = {**self.row, "status": "uploaded"}
        with bound_scope(Scope(41, 8)), \
             patch("material_uploads.service.repository.get_upload", return_value=self.row), \
             patch("material_uploads.service.repository.get_version_for_upload", return_value={"source_filename": "clip.mp4"}), \
             patch("material_uploads.service.repository.finalize", return_value=uploaded) as finalize, \
             patch("material_uploads.service.get_storage", return_value=fake_store):
            result = service.complete("upload-1", service.CompleteInput(idempotency_key="request-123"), "user")
        self.assertEqual(result["status"], "uploaded")
        finalize.assert_called_once_with("upload-1", size=12, checksum="a" * 64, backend="local", storage_key="private/key.mp4", username="user")

    def test_repository_lookup_is_bound_to_tenant_and_application(self):
        from material_uploads import repository
        cursor = unittest.mock.Mock()
        cursor.fetchone.return_value = None
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value.cursor.return_value = cursor
        with bound_scope(Scope(41, 8)), patch.object(repository, "get_app_conn", return_value=connection):
            repository.get_upload("upload-1")
        sql, args = cursor.execute.call_args.args
        self.assertIn("tenant_id=%s AND application_id=%s AND id=%s", " ".join(sql.split()))
        self.assertEqual(args, (41, 8, "upload-1"))

    def test_writer_role_rejects_read_only_user(self):
        with patch("material_catalog.routes.reader", return_value=None), self.assertRaises(HTTPException) as error:
            writer(User(username="viewer", hashed_password="", role="viewer"))
        self.assertEqual(error.exception.status_code, 403)

    def test_migration_and_schema_guard_cover_all_upload_tables(self):
        from migrations.schema_guard import APP_RESOURCE_REQUIREMENTS
        from migrations.versions import v0011_material_uploads as migration
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertTrue(migration.REVERSIBLE)
        self.assertIn("FOREIGN KEY (application_id, tenant_id)", source)
        self.assertIn("FOREIGN KEY (version_id, tenant_id, material_id)", source)
        self.assertIn("UNIQUE KEY uq_material_upload_idempotency (tenant_id, application_id, idempotency_key)", source)
        self.assertEqual(
            {"app_material_uploads", "app_material_upload_parts", "app_material_upload_audit"},
            {name for name in APP_RESOURCE_REQUIREMENTS if name.startswith("app_material_upload")},
        )


if __name__ == "__main__":
    unittest.main()
