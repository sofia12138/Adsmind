"""Contract, safety, idempotency and disposable-MySQL coverage for preflight."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException

from core.isolation import Scope, bound_scope
from platform_preflight import repository, service


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def ready_draft() -> dict:
    snapshot = {
        "contract": "ad_creation_execution_snapshot.v1",
        "draft_id": "draft-1",
        "source_revision": 2,
        "tenant_id": 11,
        "application_id": 22,
        "account_group": {"id": 1, "name": "Accounts"},
        "accounts": [{"platform": "meta", "account_id": "act_1", "account_name": "A", "status": "ACTIVE"}],
        "naming_rule": {"id": 2, "name": "Rule", "rule": {"pattern": "{platform}"}},
        "name_previews": [{"platform": "meta", "account_id": "act_1", "account_name": "A",
                           "campaign_name": "campaign", "adgroup_name": "adgroup", "creative_name": "creative"}],
        "creative_group": {"id": 3, "name": "Creative", "materials": [
            {"material_id": 4, "material_name": "Clip", "selection_mode": "latest",
             "selected_version_id": None, "effective_version_id": 9, "upload_status": "uploaded"},
        ]},
        "external_write_authorized": False,
    }
    return {"id": "draft-1", "status": "READY", "execution_snapshot": snapshot,
            "execution_snapshot_hash": canonical_hash(snapshot)}


class PlatformPreflightUnitTests(unittest.TestCase):
    def test_passed_plan_is_non_executable_and_uses_only_frozen_snapshot(self):
        draft = ready_draft()
        saved = {}

        def create_run(**kwargs):
            saved.update(kwargs)
            return {"id": "run-1", "draft_id": kwargs["draft_id"], "snapshot_hash": kwargs["snapshot_hash"],
                    "dry_run_plan": kwargs["plan"], "status": kwargs["status"]}, True

        with (
            bound_scope(Scope(11, 22)),
            patch("platform_preflight.service.draft_repository.get", return_value=draft),
            patch("platform_preflight.service.repository.get_run_by_request", return_value=None),
            patch("platform_preflight.service.repository.get_account_mapping", return_value={
                "platform": "meta", "account_id": "act_1", "external_account_id": "act_1",
                "credential_external_id": "act_1", "status": "ACTIVE",
            }),
            patch("platform_preflight.service.oauth_credential_repository.get_meta", return_value={
                "external_id": "act_1", "expires_at": None,
            }),
            patch("platform_preflight.service.repository.get_material_mapping", return_value={
                "platform_asset_id": "asset-9", "upload_status": "uploaded",
            }),
            patch("platform_preflight.service.repository.create_run", side_effect=create_run),
        ):
            row = service.run("draft-1", service.PreflightInput(request_key=str(uuid.uuid4())), "tester")
        self.assertEqual(row["status"], "PASSED")
        self.assertTrue(saved["plan"]["dry_run"])
        self.assertFalse(saved["plan"]["executable"])
        self.assertFalse(saved["plan"]["external_write_authorized"])
        self.assertEqual(saved["plan"]["operations"][0]["materials"][0]["platform_asset_id"], "asset-9")

    def test_hash_scope_mapping_credential_material_and_name_fail_closed(self):
        draft = ready_draft()
        draft["execution_snapshot"]["name_previews"][0]["campaign_name"] = "x" * 256
        with (
            bound_scope(Scope(11, 22)),
            patch("platform_preflight.service.draft_repository.get", return_value=draft),
            patch("platform_preflight.service.repository.get_run_by_request", return_value=None),
            patch("platform_preflight.service.repository.get_account_mapping", return_value=None),
            patch("platform_preflight.service.repository.create_run") as create,
        ):
            create.return_value = ({"id": "run", "draft_id": "draft-1", "snapshot_hash": draft["execution_snapshot_hash"]}, True)
            service.run("draft-1", service.PreflightInput(request_key=str(uuid.uuid4())), "tester")
        codes = {item["code"] for item in create.call_args.kwargs["blockers"]}
        self.assertIn("snapshot_hash_mismatch", codes)
        self.assertIn("account_mapping_missing", codes)
        self.assertEqual(create.call_args.kwargs["plan"]["operations"], [])

    def test_idempotency_replays_and_conflicts_without_rechecking_mutable_objects(self):
        request_key = str(uuid.uuid4())
        existing = {"id": "run", "draft_id": "draft-1", "snapshot_hash": ready_draft()["execution_snapshot_hash"]}
        with (
            bound_scope(Scope(11, 22)),
            patch("platform_preflight.service.repository.get_run_by_request", return_value=existing),
            patch("platform_preflight.service.draft_repository.get", return_value=ready_draft()),
            patch("platform_preflight.service.repository.get_account_mapping") as mapping,
        ):
            self.assertIs(service.run("draft-1", service.PreflightInput(request_key=request_key), "tester"), existing)
            mapping.assert_not_called()
        other = ready_draft()
        other["id"] = "draft-2"
        other["execution_snapshot"]["draft_id"] = "draft-2"
        other["execution_snapshot_hash"] = canonical_hash(other["execution_snapshot"])
        with (
            bound_scope(Scope(11, 22)),
            patch("platform_preflight.service.repository.get_run_by_request", return_value=existing),
            patch("platform_preflight.service.draft_repository.get", return_value=other),
        ):
            with self.assertRaises(HTTPException) as conflict:
                service.run("draft-2", service.PreflightInput(request_key=request_key), "tester")
        self.assertEqual(conflict.exception.status_code, 409)

    def test_external_write_is_rejected_at_input_and_execute_boundary(self):
        with self.assertRaises(ValueError):
            service.PreflightInput(request_key=str(uuid.uuid4()), external_write_authorized=True)
        with (
            patch("platform_preflight.service.repository.get_run", return_value={"id": "run"}),
            patch("platform_preflight.service.repository.append_audit") as audit,
        ):
            with self.assertRaises(HTTPException) as rejected:
                service.refuse_execute("run", "tester")
        self.assertEqual(rejected.exception.status_code, 409)
        audit.assert_called_once()


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class PlatformPreflightMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from db import get_app_conn
        marker = uuid.uuid4().hex[:10]
        cls.account_id = f"act_{marker}"
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES (%s,%s)", (f"preflight-{marker}", "Preflight"))
            cls.tenant_id = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_id,))
            cls.application_id = cur.lastrowid
            cur.execute("INSERT INTO app_account_groups (tenant_id,application_id,name,account_refs) VALUES (%s,%s,'Accounts','[]')", (cls.tenant_id, cls.application_id))
            account_group_id = cur.lastrowid
            cur.execute("INSERT INTO app_naming_rules (tenant_id,application_id,name,rule) VALUES (%s,%s,'Rule','{}')", (cls.tenant_id, cls.application_id))
            naming_rule_id = cur.lastrowid
            cur.execute("INSERT INTO app_creative_groups (tenant_id,application_id,name,asset_refs,created_by) VALUES (%s,%s,'Creative','[]','integration')", (cls.tenant_id, cls.application_id))
            creative_group_id = cur.lastrowid
            cls.draft_id = str(uuid.uuid4())
            snapshot = {
                "contract": "ad_creation_execution_snapshot.v1", "draft_id": cls.draft_id,
                "source_revision": 1, "tenant_id": cls.tenant_id, "application_id": cls.application_id,
                "account_group": {"id": account_group_id, "name": "Accounts"},
                "accounts": [{"platform": "meta", "account_id": cls.account_id, "account_name": "A", "status": "ACTIVE"}],
                "naming_rule": {"id": naming_rule_id, "name": "Rule", "rule": {"pattern": "{platform}"}},
                "name_previews": [{"platform": "meta", "account_id": cls.account_id, "account_name": "A",
                                   "campaign_name": "campaign", "adgroup_name": "adgroup", "creative_name": "creative"}],
                "creative_group": {"id": creative_group_id, "name": "Creative", "materials": [
                    {"material_id": 101, "material_name": "Clip", "selection_mode": "pinned",
                     "selected_version_id": 202, "effective_version_id": 202, "upload_status": "uploaded"}]},
                "external_write_authorized": False,
            }
            cur.execute(
                """INSERT INTO app_ad_creation_drafts
                   (id,tenant_id,application_id,created_by,request_key,title,status,account_group_id,
                    naming_rule_id,creative_group_id,naming_values,resolved_accounts,name_previews,
                    creative_snapshot,blocking_reasons,execution_snapshot,execution_snapshot_hash)
                   VALUES (%s,%s,%s,'integration',%s,'Ready','READY',%s,%s,%s,'{}','[]','[]','{}','[]',%s,%s)""",
                (cls.draft_id, cls.tenant_id, cls.application_id, str(uuid.uuid4()), account_group_id,
                 naming_rule_id, creative_group_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), canonical_hash(snapshot)),
            )
            cur.execute(
                """INSERT INTO app_oauth_credentials
                   (tenant_id,platform,external_id,access_token_enc) VALUES (%s,'meta',%s,'test-only')""",
                (cls.tenant_id, cls.account_id),
            )
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            for table in ("app_platform_preflight_audit", "app_platform_preflight_runs",
                          "app_platform_material_mappings", "app_platform_account_mappings"):
                cur.execute(f"DELETE FROM {table} WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_ad_creation_drafts WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_oauth_credentials WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_creative_groups WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_account_groups WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_naming_rules WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_applications WHERE tenant_id=%s", (cls.tenant_id,))
            cur.execute("DELETE FROM app_tenants WHERE id=%s", (cls.tenant_id,))
            conn.commit()

    def test_persistence_scope_idempotency_audit_and_no_write_flags(self):
        with bound_scope(Scope(self.tenant_id, self.application_id)):
            service.save_account_mapping(service.AccountMappingInput(
                platform="meta", account_id=self.account_id, external_account_id=self.account_id,
                credential_external_id=self.account_id,
            ), "integration")
            service.save_material_mapping(service.MaterialMappingInput(
                platform="meta", account_id=self.account_id, material_id=101, version_id=202,
                platform_asset_id="platform-asset-202",
            ), "integration")
            request_key = str(uuid.uuid4())
            first = service.run(self.draft_id, service.PreflightInput(request_key=request_key), "integration")
            replay = service.run(self.draft_id, service.PreflightInput(request_key=request_key), "integration")
            self.assertEqual(first["id"], replay["id"])
            self.assertEqual(first["status"], "PASSED")
            self.assertTrue(first["dry_run"])
            self.assertFalse(first["external_write_authorized"])
            self.assertFalse(first["dry_run_plan"]["executable"])
            self.assertEqual(len(repository.list_audit(first["id"])), 1)

        with bound_scope(Scope(self.tenant_id, self.application_id + 999999)):
            self.assertIsNone(repository.get_run(first["id"]))


if __name__ == "__main__":
    unittest.main()
