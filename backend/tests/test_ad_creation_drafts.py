"""Unit and disposable-MySQL integration coverage for app ad drafts."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException

from ad_creation import repository as draft_repository, service as draft_service
from core.isolation import Scope, bound_scope


class AdCreationResolutionTests(unittest.TestCase):
    def test_resolution_records_effective_version_and_explicit_account_blockers(self):
        with (
            patch("ad_creation.service.account_group_repository.get", return_value={
                "id": 1, "name": "Primary", "account_refs": [
                    {"platform": "meta", "account_id": "active"},
                    {"platform": "tiktok", "account_id": "paused"},
                    {"platform": "meta", "account_id": "missing"},
                ],
            }),
            patch("ad_creation.service.naming_rule_repository.get", return_value={
                "id": 2, "name": "Rule", "rule": {"pattern": "{platform}_{product}_{country}"},
            }),
            patch("ad_creation.service.biz_account_repository.list_all", return_value=[
                {"platform": "meta", "account_id": "active", "account_name": "A", "status": "ACTIVE", "currency": "USD", "timezone": "UTC"},
                {"platform": "tiktok", "account_id": "paused", "account_name": "B", "status": "PAUSED", "currency": "USD", "timezone": "UTC"},
            ]),
            patch("ad_creation.service.creative_group_service.get_group", return_value={
                "id": 3, "name": "Creative", "can_deliver": True, "blocking_reasons": [],
                "materials": [{"material_id": 4, "material_name": "Clip", "selection_mode": "latest",
                               "selected_version_id": None, "effective_version_id": 9,
                               "selected_version_upload_status": "uploaded"}],
            }),
        ):
            result = draft_service.resolve(
                account_group_id=1, naming_rule_id=2, creative_group_id=3,
                naming_values={"product": "show", "country": "US"},
            )
        self.assertFalse(result["ready"])
        self.assertEqual({item["code"] for item in result["blocking_reasons"]}, {"account_inactive", "account_not_owned"})
        self.assertEqual(result["creative_snapshot"]["materials"][0]["effective_version_id"], 9)
        self.assertEqual(result["name_previews"][0]["campaign_name"], "meta_show_US")

    def test_ready_snapshot_is_hashed_and_never_authorizes_external_writes(self):
        row = {
            "id": "draft", "status": "DRAFT", "revision": 4,
            "account_group_id": 1, "naming_rule_id": 2, "creative_group_id": 3,
            "naming_values": {},
        }
        resolution = {
            "ready": True, "blocking_reasons": [],
            "account_group": {"id": 1, "name": "Accounts"},
            "naming_rule": {"id": 2, "name": "Rule", "rule": {"pattern": "{platform}"}},
            "resolved_accounts": [{"platform": "meta", "account_id": "a"}],
            "name_previews": [{"account_id": "a", "campaign_name": "meta"}],
            "creative_snapshot": {"id": 3, "name": "Group", "materials": []},
        }
        captured = {}
        def save(_draft_id, **kwargs):
            captured.update(kwargs)
            return {**row, "status": "READY", "execution_snapshot": kwargs["snapshot"]}
        with (
            bound_scope(Scope(11, 22)),
            patch("ad_creation.service.repository.get", return_value=row),
            patch("ad_creation.service.resolve", return_value=resolution),
            patch("ad_creation.service.repository.mark_ready", side_effect=save),
        ):
            ready = draft_service.mark_ready("draft", 4)
        snapshot = ready["execution_snapshot"]
        self.assertFalse(snapshot["external_write_authorized"])
        self.assertEqual(snapshot["contract"], "ad_creation_execution_snapshot.v1")
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(captured["snapshot_hash"], hashlib.sha256(canonical.encode()).hexdigest())


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class AdCreationDraftsMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from db import get_app_conn, get_biz_conn
        marker = uuid.uuid4().hex[:10]
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES (%s,%s)", (f"ad-draft-a-{marker}", "Ad Draft A"))
            cls.tenant_a = cur.lastrowid
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES (%s,%s)", (f"ad-draft-b-{marker}", "Ad Draft B"))
            cls.tenant_b = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_a,))
            cls.app_a1 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'two','Two')", (cls.tenant_a,))
            cls.app_a2 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_b,))
            cls.app_b1 = cur.lastrowid
            conn.commit()
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO biz_ad_accounts
                   (tenant_id,application_id,platform,account_id,account_name,currency,timezone,status,
                    access_token,app_id,app_secret,is_default)
                   VALUES (%s,%s,'meta',%s,'Integration Account','USD','UTC','ACTIVE',NULL,'','',0)""",
                (cls.tenant_a, cls.app_a1, f"act_{marker}"),
            )
            cls.account_id = f"act_{marker}"
            conn.commit()

        from material_catalog import service as material_service
        from creative_groups import service as creative_service
        from services import account_group_service, naming_rule_service
        from db import get_app_conn
        with bound_scope(Scope(cls.tenant_a, cls.app_a1)):
            cls.account_group = account_group_service.create_group(
                name="Integration Accounts", account_refs=[{"platform": "meta", "account_id": cls.account_id}], created_by="integration"
            )
            cls.naming_rule = naming_rule_service.create_rule(
                name="Integration Rule", rule={"pattern": "{platform}_{product}_{country}", "description": ""}, created_by="integration"
            )
            master = material_service.create_master(material_service.MasterInput(name="Clip", material_type="video"), "integration")
            version = material_service.register_version(master["id"], material_service.VersionInput(
                source_filename="clip.mp4", mime_type="video/mp4", size_bytes=123,
            ), "integration")
            with get_app_conn() as conn:
                conn.cursor().execute("UPDATE material_versions SET upload_status='uploaded' WHERE id=%s", (version["id"],))
                conn.commit()
            material_service.attach(material_service.ReferenceInput(material_id=master["id"]), "integration")
            cls.creative_group = creative_service.create_group(creative_service.CreativeGroupInput(
                name="Integration Creative", materials=[{"material_id": master["id"], "selection_mode": "latest"}],
            ), "integration")
            cls.material_id = master["id"]

    @classmethod
    def tearDownClass(cls):
        from db import get_app_conn, get_biz_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM app_ad_creation_drafts WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_creative_groups WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_application_materials WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_versions WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM material_masters WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_account_groups WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_naming_rules WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_applications WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_tenants WHERE id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()
        with get_biz_conn() as conn:
            conn.cursor().execute("DELETE FROM biz_ad_accounts WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()

    def _input(self, key: str | None = None):
        return draft_service.DraftInput(
            request_key=key or str(uuid.uuid4()), title="Integration Draft",
            account_group_id=self.account_group["id"], naming_rule_id=self.naming_rule["id"],
            creative_group_id=self.creative_group["id"], naming_values={"product": "show", "country": "US"},
        )

    def test_scope_idempotency_optimistic_lock_and_immutable_ready_snapshot(self):
        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            key = str(uuid.uuid4())
            row = draft_service.create(self._input(key), "integration")
            duplicate = draft_service.create(self._input(key), "integration")
            self.assertEqual(row["id"], duplicate["id"])
            self.assertEqual(row["creative_snapshot"]["materials"][0]["effective_version_id"], self.creative_group["materials"][0]["effective_version_id"])

            update_data = self._input().model_dump()
            update_data["title"] = "Edited"
            update = draft_service.DraftUpdate(**update_data, revision=row["revision"])
            edited = draft_service.update(row["id"], update)
            with self.assertRaises(HTTPException) as stale:
                draft_service.update(row["id"], update)
            self.assertEqual(stale.exception.status_code, 409)

            ready = draft_service.mark_ready(row["id"], edited["revision"])
            replay = draft_service.mark_ready(row["id"], edited["revision"])
            self.assertEqual(ready["execution_snapshot_hash"], replay["execution_snapshot_hash"])
            self.assertFalse(ready["execution_snapshot"]["external_write_authorized"])
            with self.assertRaises(HTTPException) as immutable:
                draft_service.update(row["id"], draft_service.DraftUpdate(**self._input().model_dump(), revision=ready["revision"]))
            self.assertEqual(immutable.exception.status_code, 409)

        with bound_scope(Scope(self.tenant_a, self.app_a2)):
            self.assertIsNone(draft_repository.get(row["id"]))
            with self.assertRaises(HTTPException) as same_tenant:
                draft_service.get(row["id"])
            self.assertEqual(same_tenant.exception.status_code, 404)
        with bound_scope(Scope(self.tenant_b, self.app_b1)):
            self.assertIsNone(draft_repository.get(row["id"]))

    def test_readiness_revalidates_account_and_uploaded_version(self):
        from db import get_app_conn, get_biz_conn
        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            row = draft_service.create(self._input(), "integration")
            with get_biz_conn() as conn:
                conn.cursor().execute("UPDATE biz_ad_accounts SET status='PAUSED' WHERE tenant_id=%s AND account_id=%s", (self.tenant_a, self.account_id))
                conn.commit()
            checked = draft_service.check(row["id"])
            self.assertIn("account_inactive", {reason["code"] for reason in checked["blocking_reasons"]})
            with get_biz_conn() as conn:
                conn.cursor().execute("UPDATE biz_ad_accounts SET status='ACTIVE' WHERE tenant_id=%s AND account_id=%s", (self.tenant_a, self.account_id))
                conn.commit()
            with get_app_conn() as conn:
                conn.cursor().execute("UPDATE material_versions SET upload_status='pending_upload' WHERE tenant_id=%s AND material_id=%s", (self.tenant_a, self.material_id))
                conn.commit()
            checked = draft_service.check(row["id"])
            self.assertIn("creative_group_blocked", {reason["code"] for reason in checked["blocking_reasons"]})
            with get_app_conn() as conn:
                conn.cursor().execute("UPDATE material_versions SET upload_status='uploaded' WHERE tenant_id=%s AND material_id=%s", (self.tenant_a, self.material_id))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
