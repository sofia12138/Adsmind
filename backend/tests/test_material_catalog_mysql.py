"""Opt-in real MySQL integration coverage for the material catalog.

Run only against a dedicated disposable database with ADSMind_TEST_MYSQL=1.
"""
import os
import unittest

from fastapi import HTTPException

from core.isolation import Scope, bound_scope
from db import get_app_conn
from material_catalog import repository, service


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class MaterialCatalogMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('material-it-a','Material IT A')")
            cls.tenant_a = cur.lastrowid
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('material-it-b','Material IT B')")
            cls.tenant_b = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_a,))
            cls.app_a1 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'two','Two')", (cls.tenant_a,))
            cls.app_a2 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_b,))
            cls.app_b1 = cur.lastrowid
            cur.execute(
                """INSERT INTO drama_masters
                   (tenant_id,title,normalized_title,aliases,genres,content_fingerprint)
                   VALUES (%s,'Drama A','drama a','[]','[]',%s)""", (cls.tenant_a, "a" * 64),
            )
            cls.drama_a = cur.lastrowid
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM app_application_materials WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_versions WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_masters WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM drama_masters WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_applications WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_tenants WHERE id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()

    def test_real_crud_version_state_and_scope_boundaries(self):
        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            master = service.create_master(service.MasterInput(
                name="Opening Clip", material_type="video", drama_id=self.drama_a, tags=["opening"]
            ), "integration")
            version = service.register_version(master["id"], service.VersionInput(
                source_filename="opening.mp4", mime_type="video/mp4", size_bytes=2048,
                checksum_sha256="b" * 64, width=1080, height=1920, duration_ms=12000,
            ), "integration")
            self.assertEqual(version["version_number"], 1)
            self.assertEqual(version["upload_status"], "pending_upload")
            self.assertFalse(version["upload"]["available"])
            reference = service.attach(service.ReferenceInput(material_id=master["id"]), "integration")
            self.assertEqual(reference["application_id"], self.app_a1)

        with bound_scope(Scope(self.tenant_b, self.app_b1)):
            self.assertIsNone(repository.get_master(master["id"]))
            with self.assertRaises(HTTPException) as error:
                service.attach(service.ReferenceInput(material_id=master["id"]), "integration")
            self.assertEqual(error.exception.status_code, 404)

        with bound_scope(Scope(self.tenant_a, self.app_a2)):
            self.assertEqual(repository.get_master(master["id"])["name"], "Opening Clip")
            self.assertIsNone(repository.get_reference(master["id"]))
            with self.assertRaises(HTTPException) as error:
                service.update_reference(master["id"], service.ReferenceUpdate(status="paused"))
            self.assertEqual(error.exception.status_code, 404)

        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            pinned = service.update_reference(master["id"], service.ReferenceUpdate(
                selection_mode="pinned", selected_version_id=version["id"]
            ))
            self.assertEqual(pinned["selected_version_id"], version["id"])
            service.detach(master["id"])
            self.assertIsNone(repository.get_reference(master["id"]))


if __name__ == "__main__":
    unittest.main()
