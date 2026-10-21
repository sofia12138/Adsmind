"""Opt-in integration coverage against a dedicated disposable MySQL database."""
import os
import unittest

from fastapi import HTTPException

from core.isolation import Scope, bound_scope
from creative_groups import repository as group_repository, service as group_service
from db import get_app_conn
from material_catalog import service as material_service


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class CreativeGroupsMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('creative-it-a','Creative IT A')")
            cls.tenant_a = cur.lastrowid
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES ('creative-it-b','Creative IT B')")
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
            cur.execute("DELETE FROM app_creative_groups WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_application_materials WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_versions WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_masters WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_applications WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_tenants WHERE id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()

    def test_latest_pinned_draft_state_and_scope_isolation(self):
        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            master = material_service.create_master(
                material_service.MasterInput(name="Opening", material_type="video"), "integration"
            )
            v1 = material_service.register_version(
                master["id"], material_service.VersionInput(
                    source_filename="opening-v1.mp4", mime_type="video/mp4", size_bytes=100,
                ), "integration",
            )
            with get_app_conn() as conn:
                conn.cursor().execute(
                    "UPDATE material_versions SET upload_status='uploaded' WHERE id=%s AND tenant_id=%s",
                    (v1["id"], self.tenant_a),
                )
                conn.commit()
            material_service.attach(material_service.ReferenceInput(material_id=master["id"]), "integration")
            latest = group_service.create_group(group_service.CreativeGroupInput(
                name="Latest", materials=[{"material_id": master["id"], "selection_mode": "latest"}],
            ), "integration")
            pinned = group_service.create_group(group_service.CreativeGroupInput(
                name="Pinned", materials=[{
                    "material_id": master["id"], "selection_mode": "pinned", "selected_version_id": v1["id"],
                }],
            ), "integration")
            self.assertTrue(latest["can_deliver"])
            self.assertTrue(pinned["can_deliver"])

            material_service.register_version(
                master["id"], material_service.VersionInput(
                    source_filename="opening-v2.mp4", mime_type="video/mp4", size_bytes=101,
                ), "integration",
            )
            self.assertFalse(group_service.get_group(latest["id"])["can_deliver"])
            self.assertTrue(group_service.get_group(pinned["id"])["can_deliver"])

            # The JSON compatibility payload preserves the contract across a
            # deliberate 0007 rollback/re-upgrade and is backfilled safely.
            from migrations.versions import v0007_creative_groups as migration
            migration.downgrade()
            migration.upgrade()
            self.assertFalse(group_service.get_group(latest["id"])["can_deliver"])
            self.assertTrue(group_service.get_group(pinned["id"])["can_deliver"])

        with bound_scope(Scope(self.tenant_a, self.app_a2)):
            self.assertIsNone(group_repository.get(latest["id"]))
            with self.assertRaises(HTTPException) as same_tenant_foreign:
                group_service.create_group(group_service.CreativeGroupInput(
                    name="Foreign", materials=[{"material_id": master["id"]}],
                ), "integration")
            self.assertEqual(same_tenant_foreign.exception.status_code, 404)

        with bound_scope(Scope(self.tenant_b, self.app_b1)):
            self.assertIsNone(group_repository.get(latest["id"]))
            with self.assertRaises(HTTPException) as cross_tenant:
                group_service.create_group(group_service.CreativeGroupInput(
                    name="Foreign", materials=[{"material_id": master["id"]}],
                ), "integration")
            self.assertEqual(cross_tenant.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
