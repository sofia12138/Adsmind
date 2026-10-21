"""Safety, determinism, isolation and MySQL coverage for automation rules."""
from __future__ import annotations

import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException

from automation_rules import repository, service
from core.isolation import Scope, bound_scope


def rule_input(**overrides):
    payload = {
        "name": "READY 人工复核",
        "description": "只生成审核建议",
        "status": "ACTIVE",
        "definition": {"conditions": [{
            "source": "ad_draft", "field": "status", "operator": "equals", "value": "READY",
            "quantifier": "any", "outcome": "review_required", "code": "ready_review",
            "message": "READY 草稿仍需人工复核",
        }]},
    }
    payload.update(overrides)
    return service.RuleCreate(**payload)


class AutomationRuleUnitTests(unittest.TestCase):
    def test_definition_rejects_unapproved_fields_and_external_write(self):
        payload = rule_input().model_dump()
        payload["definition"]["conditions"][0]["field"] = "access_token"
        with self.assertRaises(ValueError):
            service.RuleCreate(**payload)
        with self.assertRaises(ValueError):
            service.EvaluationInput(ad_draft_ids=["draft-1"], external_write_authorized=True)

    def test_only_structured_review_or_blocking_outcomes_are_possible(self):
        definition = {"conditions": [
            {"source": "ad_draft", "field": "status", "operator": "equals", "value": "READY",
             "quantifier": "any", "outcome": "review_required", "code": "review", "message": "review"},
            {"source": "platform_preflight", "field": "status", "operator": "equals", "value": "BLOCKED",
             "quantifier": "any", "outcome": "blocking_reason", "code": "preflight_blocked", "message": "blocked"},
        ]}
        snapshot = {"ad_draft": [{"status": "READY"}], "platform_preflight": [{"status": "BLOCKED"}]}
        blockers, recommendations = service._evaluate(definition, snapshot)
        self.assertEqual([item["code"] for item in recommendations], ["review"])
        self.assertEqual([item["code"] for item in blockers], ["preflight_blocked"])

    def test_same_rule_version_and_snapshot_replays_stably(self):
        rule = {"id": "rule-1", "status": "ACTIVE", "current_version": 3, "rule_version_id": 9,
                "definition_hash": "d" * 64, "definition": rule_input().definition.model_dump()}
        snapshot = {"contract": "automation_rule_input_snapshot.v1", "ad_draft": [{"id": "d", "status": "READY"}],
                    "material": [], "creative_group": [], "platform_preflight": [], "dry_run": True,
                    "external_write_authorized": False}
        existing = {"id": "evaluation-1", "status": "REVIEW_REQUIRED", "dry_run": True,
                    "external_write_authorized": False}
        with (
            bound_scope(Scope(11, 22)),
            patch("automation_rules.service.repository.get_rule", return_value=rule),
            patch("automation_rules.service.build_snapshot", return_value=snapshot),
            patch("automation_rules.service.repository.get_evaluation_by_key", side_effect=[None, existing]) as find,
            patch("automation_rules.service.repository.create_evaluation", return_value=(existing, True)) as create,
        ):
            first = service.evaluate("rule-1", None, service.EvaluationInput(ad_draft_ids=["d"]), "tester")
            replay = service.evaluate("rule-1", None, service.EvaluationInput(ad_draft_ids=["d"]), "tester")
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(find.call_args_list[0].args[0], find.call_args_list[1].args[0])
        create.assert_called_once()
        self.assertTrue(first["dry_run"])
        self.assertFalse(first["external_write_authorized"])

    def test_missing_required_source_fails_closed(self):
        definition = rule_input().definition.model_dump()
        blockers, recommendations = service._evaluate(definition, {"ad_draft": []})
        self.assertEqual(recommendations, [])
        self.assertEqual(blockers[0]["code"], "input_source_missing")


@unittest.skipUnless(os.getenv("ADSMIND_TEST_MYSQL") == "1", "requires disposable MySQL")
class AutomationRuleMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from db import get_app_conn
        marker = uuid.uuid4().hex[:10]
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES (%s,'Rules A')", (f"rules-a-{marker}",))
            cls.tenant_a = cur.lastrowid
            cur.execute("INSERT INTO app_tenants (slug,name) VALUES (%s,'Rules B')", (f"rules-b-{marker}",))
            cls.tenant_b = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_a,))
            cls.app_a1 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'two','Two')", (cls.tenant_a,))
            cls.app_a2 = cur.lastrowid
            cur.execute("INSERT INTO app_applications (tenant_id,slug,name) VALUES (%s,'one','One')", (cls.tenant_b,))
            cls.app_b1 = cur.lastrowid
            cur.execute("INSERT INTO drama_masters (tenant_id,title,normalized_title,aliases,genres,content_fingerprint) VALUES (%s,'D','d','[]','[]',%s)", (cls.tenant_a, marker * 6 + 'xxxx'))
            drama_id = cur.lastrowid
            cur.execute("INSERT INTO material_masters (tenant_id,drama_id,name,material_type,tags,status,created_by) VALUES (%s,%s,'Clip','video','[]','active','integration')", (cls.tenant_a, drama_id))
            cls.material_id = cur.lastrowid
            cur.execute("INSERT INTO material_versions (tenant_id,material_id,version_number,source_filename,file_extension,mime_type,size_bytes,checksum_sha256,upload_status,storage_backend,storage_key,metadata_json,created_by) VALUES (%s,%s,1,'clip.mp4','mp4','video/mp4',1,%s,'uploaded','test','test','{}','integration')", (cls.tenant_a, cls.material_id, 'a' * 64))
            version_id = cur.lastrowid
            cur.execute("UPDATE material_masters SET latest_version_number=1 WHERE id=%s", (cls.material_id,))
            cur.execute("INSERT INTO app_application_materials (tenant_id,application_id,material_id,selected_version_id,selection_mode,status,created_by) VALUES (%s,%s,%s,%s,'pinned','selected','integration')", (cls.tenant_a, cls.app_a1, cls.material_id, version_id))
            conn.commit()
        with bound_scope(Scope(cls.tenant_a, cls.app_a1)):
            cls.rule = service.create_rule(service.RuleCreate(**{
                "name": f"Uploaded review {marker}", "definition": {"conditions": [{
                    "source": "material", "field": "selected_version_upload_status", "operator": "equals",
                    "value": "uploaded", "quantifier": "all", "outcome": "review_required",
                    "code": "uploaded_review", "message": "上传状态仅供人工复核",
                }]},
            }), "integration")

    @classmethod
    def tearDownClass(cls):
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            for table in ("app_automation_rule_audit", "app_automation_rule_recommendations",
                          "app_automation_rule_evaluations", "app_automation_rule_versions", "app_automation_rules"):
                cur.execute(f"DELETE FROM {table} WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_application_materials WHERE tenant_id=%s", (cls.tenant_a,))
            cur.execute("DELETE FROM material_versions WHERE tenant_id=%s", (cls.tenant_a,))
            cur.execute("DELETE FROM material_masters WHERE tenant_id=%s", (cls.tenant_a,))
            cur.execute("DELETE FROM drama_masters WHERE tenant_id=%s", (cls.tenant_a,))
            cur.execute("DELETE FROM app_applications WHERE tenant_id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            cur.execute("DELETE FROM app_tenants WHERE id IN (%s,%s)", (cls.tenant_a, cls.tenant_b))
            conn.commit()

    def test_persistence_idempotency_append_only_audit_and_scope(self):
        data = service.EvaluationInput(material_ids=[self.material_id])
        with bound_scope(Scope(self.tenant_a, self.app_a1)):
            first = service.evaluate(self.rule["id"], None, data, "integration")
            replay = service.evaluate(self.rule["id"], None, data, "integration")
            self.assertEqual(first["id"], replay["id"])
            self.assertEqual(first["status"], "REVIEW_REQUIRED")
            self.assertTrue(first["dry_run"])
            self.assertFalse(first["external_write_authorized"])
            self.assertEqual(len(first["recommendations"]), 1)
            self.assertEqual(len(repository.list_audit("evaluation", first["id"])), 1)
        with bound_scope(Scope(self.tenant_a, self.app_a2)):
            self.assertIsNone(repository.get_rule(self.rule["id"]))
            self.assertIsNone(repository.get_evaluation(first["id"]))
            with self.assertRaises(HTTPException) as app_error:
                service.evaluate(self.rule["id"], None, data, "integration")
            self.assertEqual(app_error.exception.status_code, 404)
        with bound_scope(Scope(self.tenant_b, self.app_b1)):
            self.assertIsNone(repository.get_rule(self.rule["id"]))
            self.assertIsNone(repository.get_evaluation(first["id"]))

    def test_database_constraints_reject_write_authorization(self):
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            with self.assertRaises(Exception):
                cur.execute(
                    """INSERT INTO app_automation_rule_evaluations
                       (id,tenant_id,application_id,rule_id,rule_version_id,input_snapshot,input_snapshot_hash,
                        evaluation_key,status,blocking_reasons,dry_run,external_write_authorized,created_by)
                       VALUES (%s,%s,%s,%s,%s,'{}',%s,%s,'CLEAR','[]',0,1,'integration')""",
                    (str(uuid.uuid4()), self.tenant_a, self.app_a1, self.rule["id"], self.rule["rule_version_id"],
                     'b' * 64, 'c' * 64),
                )
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
