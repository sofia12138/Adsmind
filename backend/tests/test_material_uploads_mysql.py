"""Opt-in disposable MySQL end-to-end coverage for upload state transitions."""
import hashlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from core.isolation import Scope, bound_scope
from db import get_app_conn
from material_catalog import service as catalog_service
from material_uploads import repository, service
from material_uploads.storage import LocalStorage


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class MaterialUploadsMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('upload-it-a','Upload IT A')")
            cls.tenant_a = cur.lastrowid
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('upload-it-b','Upload IT B')")
            cls.tenant_b = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_a,))
            cls.app_a1 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'two','Two')", (cls.tenant_a,))
            cls.app_a2 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_b,))
            cls.app_b1 = cur.lastrowid
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            for table in ("app_material_upload_audit", "app_material_upload_parts", "app_material_uploads"):
                cur.execute(f"DELETE FROM {table} WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_versions WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_masters WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_applications WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_tenants WHERE id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()
        cls.temp.cleanup()

    def test_direct_upload_verification_idempotency_and_scope(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"mysql-integration"
        checksum = hashlib.sha256(payload).hexdigest()
        storage = LocalStorage(self.temp.name)
        with bound_scope(Scope(self.tenant_a, self.app_a1)), patch("material_uploads.service.get_storage", return_value=storage):
            master = catalog_service.create_master(catalog_service.MasterInput(name="Upload", material_type="image"), "integration")
            version = catalog_service.register_version(master["id"], catalog_service.VersionInput(source_filename="proof.png", mime_type="image/png", size_bytes=len(payload), checksum_sha256=checksum), "integration")
            upload = service.prepare(service.PrepareInput(material_id=master["id"], version_id=version["id"], idempotency_key="mysql-upload-proof", mode="direct"), "integration")
            service.upload_direct(upload["id"], io.BytesIO(payload), "integration")
            completed = service.complete(upload["id"], service.CompleteInput(idempotency_key="mysql-upload-proof"), "integration")
            repeated = service.complete(upload["id"], service.CompleteInput(idempotency_key="mysql-upload-proof"), "integration")
            self.assertEqual(completed["status"], "uploaded")
            self.assertEqual(repeated["status"], "uploaded")
            self.assertEqual(repository.get_version_for_upload(master["id"], version["id"])["upload_status"], "uploaded")

        with bound_scope(Scope(self.tenant_a, self.app_a2)):
            self.assertIsNone(repository.get_upload(upload["id"]))
        with bound_scope(Scope(self.tenant_b, self.app_b1)):
            self.assertIsNone(repository.get_upload(upload["id"]))


if __name__ == "__main__":
    unittest.main()
