"""Opt-in real HTTP acceptance for stages 0, 1 and 3.

Run only against a disposable local backend and database by setting
``ADSMIND_FOUNDATION_HTTP_BASE``. The fixtures intentionally remain available
after the run so the same identities can be used for browser acceptance.
"""
from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request

from auth import create_token
from core.isolation import Scope, bound_scope
from db import get_app_conn, get_biz_conn
from repositories import (
    application_repository,
    tenant_member_repository,
    tenant_repository,
    user_repository,
)
from services import panel_service
from services.user_service import hash_password


BASE = os.getenv("ADSMIND_FOUNDATION_HTTP_BASE", "")
PASSWORD = "Acceptance-1234"


def request(method: str, path: str, body=None, headers=None):
    payload = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        BASE + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(call, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


@unittest.skipUnless(BASE, "requires the isolated local HTTP server")
class FoundationCatalogGroupsHTTPAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tenant_a = tenant_repository.create(
            slug="foundation-audit-a", name="Foundation Audit A", plan_id="pro"
        )["id"]
        cls.tenant_b = tenant_repository.create(
            slug="foundation-audit-b", name="Foundation Audit B", plan_id="pro"
        )["id"]
        cls.app_a1 = application_repository.create(
            cls.tenant_a, "Foundation App One", slug="foundation-one", is_default=True
        )["id"]
        cls.app_a2 = application_repository.create(
            cls.tenant_a, "Foundation App Two", slug="foundation-two"
        )["id"]
        cls.app_b1 = application_repository.create(
            cls.tenant_b, "Foreign Foundation App", slug="foreign-foundation", is_default=True
        )["id"]

        def make_user(username: str, global_role: str, tenant_id: int, tenant_role: str,
                      app_id: int | None = None, app_role: str | None = None):
            row = user_repository.create(
                username=username,
                password_hash=hash_password(PASSWORD),
                role=global_role,
                display_name=username.split("@")[0],
                assigned_accounts=[],
            )
            tenant_member_repository.ensure_member(tenant_id, row["id"], tenant_role)
            if app_id and app_role:
                application_repository.add_member(app_id, row["id"], app_role)
            token = create_token(username, global_role, tenant_id=tenant_id)
            return row, token

        cls.owner, owner_token = make_user(
            "foundation-owner@example.test", "admin", cls.tenant_a, "owner"
        )
        cls.admin, admin_token = make_user(
            "foundation-admin@example.test", "optimizer", cls.tenant_a, "admin"
        )
        cls.editor, editor_token = make_user(
            "foundation-editor@example.test", "optimizer", cls.tenant_a, "member",
            cls.app_a1, "editor",
        )
        cls.viewer, viewer_token = make_user(
            "foundation-viewer@example.test", "viewer", cls.tenant_a, "member",
            cls.app_a1, "viewer",
        )
        cls.member, member_token = make_user(
            "foundation-member@example.test", "optimizer", cls.tenant_a, "member"
        )
        cls.foreign_owner, foreign_token = make_user(
            "foundation-foreign@example.test", "admin", cls.tenant_b, "owner"
        )

        cls.owner_h = {"Authorization": "Bearer " + owner_token, "X-Application-Id": str(cls.app_a1)}
        cls.admin_h = {"Authorization": "Bearer " + admin_token, "X-Application-Id": str(cls.app_a1)}
        cls.editor_h = {"Authorization": "Bearer " + editor_token, "X-Application-Id": str(cls.app_a1)}
        cls.viewer_h = {"Authorization": "Bearer " + viewer_token, "X-Application-Id": str(cls.app_a1)}
        cls.member_h = {"Authorization": "Bearer " + member_token, "X-Application-Id": str(cls.app_a1)}
        cls.member_list_h = {"Authorization": "Bearer " + member_token}
        cls.foreign_h = {"Authorization": "Bearer " + foreign_token, "X-Application-Id": str(cls.app_b1)}
        cls.owner_a2_h = {**cls.owner_h, "X-Application-Id": str(cls.app_a2)}
        cls.editor_a2_h = {**cls.editor_h, "X-Application-Id": str(cls.app_a2)}

        panel_service.set_user_panels(
            cls.viewer["username"], ["creatives", "account_groups", "naming_rules", "creative_groups"]
        )

        with get_biz_conn() as conn:
            cur = conn.cursor()
            for tenant_id, application_id, account_id in (
                (cls.tenant_a, cls.app_a1, "foundation-account-a1"),
                (cls.tenant_a, cls.app_a2, "foundation-account-a2"),
                (cls.tenant_b, cls.app_b1, "foundation-account-b1"),
            ):
                cur.execute(
                    """INSERT INTO biz_ad_accounts
                       (tenant_id,application_id,platform,account_id,account_name,currency,timezone,status,app_id,app_secret)
                       VALUES (%s,%s,'tiktok',%s,%s,'USD','Asia/Shanghai','ACTIVE','','')""",
                    (tenant_id, application_id, account_id, account_id),
                )
            conn.commit()

    def test_a_tenant_application_role_and_user_override_boundaries(self):
        self.assertEqual(request("GET", "/api/users/me")[0], 401)
        self.assertEqual(request("GET", "/api/applications", headers=self.owner_h)[0], 200)
        status, viewer_apps = request("GET", "/api/applications", headers=self.viewer_h)
        self.assertEqual(status, 200)
        self.assertEqual([app["id"] for app in viewer_apps], [self.app_a1])
        self.assertEqual(request("GET", "/api/applications", headers=self.member_list_h), (200, []))
        self.assertEqual(
            request("GET", f"/api/applications/{self.app_a2}", headers=self.viewer_h)[0], 404
        )
        self.assertEqual(
            request("GET", f"/api/applications/{self.app_a2}/members", headers=self.viewer_h)[0], 404
        )
        self.assertEqual(
            request("GET", f"/api/applications/{self.app_a2}/ad-accounts", headers=self.viewer_h)[0], 404
        )
        self.assertEqual(
            request("GET", f"/api/applications/{self.app_b1}", headers=self.owner_h)[0], 404
        )
        self.assertEqual(request("GET", "/api/users/me", headers=self.editor_a2_h)[0], 403)
        self.assertEqual(request("GET", "/api/users/me", headers=self.member_h)[0], 403)

        forged = create_token(self.owner["username"], "admin", tenant_id=self.tenant_b)
        self.assertEqual(
            request("GET", "/api/users/me", headers={
                "Authorization": "Bearer " + forged,
                "X-Application-Id": str(self.app_b1),
            })[0],
            403,
        )
        status, me = request("GET", "/api/users/me", headers={**self.owner_h, "X-Tenant-Id": str(self.tenant_b)})
        self.assertEqual(status, 200)
        self.assertEqual(me["tenant"]["id"], self.tenant_a)

        status, access = request("GET", "/api/application-settings/access", headers=self.viewer_h)
        self.assertEqual((status, access["role"], access["can_write"]), (200, "viewer", False))
        status, access = request("GET", "/api/application-settings/access", headers=self.editor_h)
        self.assertEqual((status, access["role"], access["can_write"]), (200, "editor", True))
        self.assertEqual(
            request("POST", "/api/account-groups", {
                "name": "viewer denied", "account_refs": [{"platform": "tiktok", "account_id": "foundation-account-a1"}],
            }, self.viewer_h)[0],
            403,
        )

        status, override = request(
            "GET", f"/api/panels/users/{self.viewer['username']}", headers=self.owner_h
        )
        self.assertEqual(status, 200)
        self.assertTrue(override["has_override"])
        status, mine = request("GET", "/api/panels/my", headers=self.viewer_h)
        self.assertEqual(status, 200)
        self.assertEqual(
            set(mine["allowed_panels"]),
            {"creatives", "account_groups", "naming_rules", "creative_groups"},
        )

        status, created = request("POST", "/api/applications", {
            "name": "Lifecycle App", "slug": "lifecycle-app", "platform_type": "multi",
        }, self.owner_h)
        self.assertEqual(status, 200)
        lifecycle_id = created["id"]
        status, updated = request("PUT", f"/api/applications/{lifecycle_id}", {
            "name": "Lifecycle App Updated"
        }, self.owner_h)
        self.assertEqual((status, updated["name"]), (200, "Lifecycle App Updated"))
        self.assertEqual(request("DELETE", f"/api/applications/{lifecycle_id}", headers=self.owner_h)[0], 200)
        self.assertEqual(request("GET", "/api/users/me", headers={
            **self.owner_h, "X-Application-Id": str(lifecycle_id)
        })[0], 403)
        self.assertEqual(request("POST", f"/api/applications/{lifecycle_id}/restore", headers=self.owner_h)[0], 200)

    def test_b_drama_master_reference_revision_and_scope(self):
        body = {
            "title": "  Foundation   Drama ",
            "aliases": ["Foundation Alias", " foundation alias ", "基础剧"],
            "original_language": "en",
            "region": "US",
            "genres": ["Drama", "Drama"],
            "synopsis": "Acceptance drama",
            "cover_url": "https://example.test/cover.jpg",
        }
        status, master = request("POST", "/api/drama-catalog/masters", body, self.editor_h)
        self.assertEqual(status, 201, master)
        self.assertEqual(master["aliases"], ["Foundation Alias", "基础剧"])
        self.__class__.drama_id = master["id"]

        status, found = request(
            "GET", "/api/drama-catalog/masters?query=Foundation%20Alias&page=1&page_size=1",
            headers=self.viewer_h,
        )
        self.assertEqual(status, 200)
        self.assertEqual(found["total"], 1)
        self.assertEqual(request("POST", "/api/drama-catalog/masters", body, self.editor_h)[0], 409)

        update = {**body, "title": "Foundation Drama Updated", "revision": master["revision"]}
        status, revised = request("PUT", f"/api/drama-catalog/masters/{master['id']}", update, self.editor_h)
        self.assertEqual(status, 200)
        self.assertEqual(revised["revision"], master["revision"] + 1)
        self.assertEqual(
            request("PUT", f"/api/drama-catalog/masters/{master['id']}", update, self.editor_h)[0], 409
        )
        self.assertEqual(request("GET", f"/api/drama-catalog/masters/{master['id']}", headers=self.foreign_h)[0], 404)
        self.assertEqual(request("POST", "/api/drama-catalog/masters", body, self.viewer_h)[0], 403)

        status, ref_a1 = request("POST", "/api/drama-catalog/references", {
            "drama_id": master["id"], "display_title": "App One Drama", "status": "active", "notes": "a1"
        }, self.editor_h)
        self.assertEqual(status, 201)
        self.assertEqual(ref_a1["display_title"], "App One Drama")
        self.assertEqual(request("GET", "/api/drama-catalog/references", headers=self.owner_a2_h)[1]["total"], 0)
        self.assertEqual(request("POST", "/api/drama-catalog/references", {
            "drama_id": master["id"], "display_title": "App Two Drama"
        }, self.owner_a2_h)[0], 201)
        self.assertEqual(request("DELETE", f"/api/drama-catalog/references/{master['id']}", headers=self.owner_a2_h)[0], 200)
        self.assertEqual(request("GET", f"/api/drama-catalog/masters/{master['id']}", headers=self.owner_h)[0], 200)
        self.assertEqual(request("DELETE", f"/api/drama-catalog/masters/{master['id']}", headers=self.owner_h)[0], 409)

        status, second = request("POST", "/api/drama-catalog/masters", {
            **body, "title": "Foundation Drama Second", "aliases": ["Second Alias"]
        }, self.editor_h)
        self.assertEqual(status, 201)
        status, paged = request("GET", "/api/drama-catalog/masters?page=1&page_size=1", headers=self.viewer_h)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(paged["total"], 2)
        self.assertEqual(len(paged["items"]), 1)

        self.assertEqual(request("DELETE", f"/api/drama-catalog/references/{master['id']}", headers=self.editor_h)[0], 200)
        self.assertEqual(request("DELETE", f"/api/drama-catalog/masters/{master['id']}", headers=self.editor_h)[0], 200)

    def test_c_account_naming_and_creative_groups(self):
        valid_ref = [{"platform": "tiktok", "account_id": "foundation-account-a1"}]
        status, group = request("POST", "/api/account-groups", {
            "name": "Foundation Account Group", "account_refs": valid_ref,
        }, self.editor_h)
        self.assertEqual(status, 201)
        group = group["data"]
        self.assertEqual(request("POST", "/api/account-groups", {
            "name": "Foundation Account Group", "account_refs": valid_ref,
        }, self.editor_h)[0], 409)
        self.assertEqual(request("POST", "/api/account-groups", {
            "name": "Foreign Account Group",
            "account_refs": [{"platform": "tiktok", "account_id": "foundation-account-a2"}],
        }, self.editor_h)[0], 404)
        self.assertEqual(request("GET", f"/api/account-groups/{group['id']}", headers=self.owner_a2_h)[0], 404)
        self.assertEqual(request("GET", "/api/account-groups", headers=self.viewer_h)[0], 200)
        status, updated_group = request("PUT", f"/api/account-groups/{group['id']}", {
            "name": "Foundation Account Group Updated", "account_refs": valid_ref,
        }, self.editor_h)
        self.assertEqual((status, updated_group["data"]["name"]), (200, "Foundation Account Group Updated"))

        rule_body = {
            "name": "Foundation Naming Rule",
            "rule": {"pattern": "{platform}_{product}_{country}_{date}", "description": "Acceptance"},
        }
        status, rule = request("POST", "/api/naming-rules", rule_body, self.editor_h)
        self.assertEqual(status, 201)
        rule = rule["data"]
        self.assertEqual(rule["rule"]["fields"], ["platform", "product", "country", "date"])
        self.assertEqual(request("POST", "/api/naming-rules", rule_body, self.editor_h)[0], 409)
        self.assertEqual(request("POST", "/api/naming-rules", {
            "name": "Invalid Rule", "rule": {"pattern": "{tenant_secret}", "description": ""},
        }, self.editor_h)[0], 422)
        self.assertEqual(request("GET", f"/api/naming-rules/{rule['id']}", headers=self.owner_a2_h)[0], 404)
        self.assertEqual(request("GET", "/api/naming-rules", headers=self.viewer_h)[0], 200)

        status, material = request("POST", "/api/material-catalog/masters", {
            "name": "Foundation Creative Material", "material_type": "video", "tags": ["audit"]
        }, self.editor_h)
        self.assertEqual(status, 201)
        status, v1 = request("POST", f"/api/material-catalog/masters/{material['id']}/versions", {
            "source_filename": "foundation-v1.mp4", "mime_type": "video/mp4", "size_bytes": 101
        }, self.editor_h)
        self.assertEqual(status, 201)
        self.assertEqual(request("POST", "/api/material-catalog/references", {
            "material_id": material["id"], "status": "selected", "notes": "audit"
        }, self.editor_h)[0], 201)
        status, latest = request("POST", "/api/creative-groups", {
            "name": "Foundation Latest Group",
            "materials": [{"material_id": material["id"], "selection_mode": "latest", "selected_version_id": None}],
        }, self.editor_h)
        self.assertEqual(status, 201)
        latest = latest["data"]
        self.assertFalse(latest["can_deliver"])

        with get_app_conn() as conn:
            conn.cursor().execute(
                "UPDATE material_versions SET upload_status='uploaded' WHERE id=%s", (v1["id"],)
            )
            conn.commit()
        self.assertTrue(request("GET", f"/api/creative-groups/{latest['id']}", headers=self.viewer_h)[1]["data"]["can_deliver"])
        status, pinned = request("POST", "/api/creative-groups", {
            "name": "Foundation Pinned Group",
            "materials": [{"material_id": material["id"], "selection_mode": "pinned", "selected_version_id": v1["id"]}],
        }, self.editor_h)
        self.assertEqual(status, 201)
        pinned = pinned["data"]
        status, _ = request("POST", f"/api/material-catalog/masters/{material['id']}/versions", {
            "source_filename": "foundation-v2.mp4", "mime_type": "video/mp4", "size_bytes": 102
        }, self.editor_h)
        self.assertEqual(status, 201)
        self.assertFalse(request("GET", f"/api/creative-groups/{latest['id']}", headers=self.viewer_h)[1]["data"]["can_deliver"])
        self.assertTrue(request("GET", f"/api/creative-groups/{pinned['id']}", headers=self.viewer_h)[1]["data"]["can_deliver"])
        self.assertEqual(request("GET", f"/api/creative-groups/{latest['id']}", headers=self.owner_a2_h)[0], 404)
        self.assertEqual(request("POST", "/api/creative-groups", {
            "name": "Cross App Group", "materials": [{"material_id": material["id"], "selection_mode": "latest"}],
        }, self.owner_a2_h)[0], 404)
        self.assertEqual(request("POST", "/api/creative-groups", {
            "name": "Viewer Denied Group", "materials": [{"material_id": material["id"], "selection_mode": "latest"}],
        }, self.viewer_h)[0], 403)

        self.__class__.account_group_id = group["id"]
        self.__class__.naming_rule_id = rule["id"]
        self.__class__.material_id = material["id"]
        self.__class__.latest_group_id = latest["id"]
        self.__class__.pinned_group_id = pinned["id"]


if __name__ == "__main__":
    unittest.main()
