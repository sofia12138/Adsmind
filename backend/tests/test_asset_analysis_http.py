"""Opt-in real HTTP acceptance for the read-only asset analysis surface."""
from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
import uuid

from auth import create_token
from db import get_app_conn, get_biz_conn
from repositories import application_repository, tenant_member_repository, user_repository
from services.user_service import hash_password


BASE = os.getenv("ADSMIND_HTTP_BASE_URL", "")
PASSWORD = "Acceptance-1234"


def request(method: str, path: str, body=None, headers=None):
    payload = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        BASE + path, data=payload, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(call, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@unittest.skipUnless(BASE, "requires a running isolated local HTTP server")
class AssetAnalysisHTTPAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = "analysis-http-" + uuid.uuid4().hex[:10]
        status, owner = request("POST", "/api/auth/register", {
            "email": cls.prefix + "@example.test", "password": PASSWORD,
            "company_name": "Analysis HTTP Acceptance", "plan_id": "pro",
        })
        assert status == 200, owner
        cls.owner_username = owner["user"]["username"]
        cls.tenant_id = int(owner["tenant"]["id"])
        cls.application_id = int(owner["application"]["id"])
        cls.owner_headers = {
            "Authorization": "Bearer " + owner["token"],
            "X-Application-Id": str(cls.application_id),
        }

        cls.other_application_id = int(application_repository.create(cls.tenant_id, "Other analysis app")["id"])
        cls.other_app_headers = {**cls.owner_headers, "X-Application-Id": str(cls.other_application_id)}

        viewer = user_repository.create(
            username=cls.prefix + "-viewer@example.test", password_hash=hash_password(PASSWORD),
            role="optimizer", display_name="Analysis Viewer", assigned_accounts=[],
        )
        tenant_member_repository.ensure_member(cls.tenant_id, viewer["id"], "member")
        application_repository.add_member(cls.application_id, viewer["id"], "viewer")
        cls.viewer_username = viewer["username"]
        cls.viewer_headers = {
            "Authorization": "Bearer " + create_token(viewer["username"], "optimizer", tenant_id=cls.tenant_id),
            "X-Application-Id": str(cls.application_id),
        }

        outsider = user_repository.create(
            username=cls.prefix + "-outsider@example.test", password_hash=hash_password(PASSWORD),
            role="optimizer", display_name="No App Access", assigned_accounts=[],
        )
        tenant_member_repository.ensure_member(cls.tenant_id, outsider["id"], "member")
        cls.outsider_headers = {
            "Authorization": "Bearer " + create_token(outsider["username"], "optimizer", tenant_id=cls.tenant_id),
            "X-Application-Id": str(cls.application_id),
        }

        status, foreign = request("POST", "/api/auth/register", {
            "email": cls.prefix + "-foreign@example.test", "password": PASSWORD,
            "company_name": "Foreign Analysis Acceptance", "plan_id": "pro",
        })
        assert status == 200, foreign
        cls.foreign_headers = {
            "Authorization": "Bearer " + foreign["token"],
            "X-Application-Id": str(foreign["application"]["id"]),
        }
        cls._seed()

    @classmethod
    def _seed(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO drama_masters
                   (tenant_id,title,normalized_title,aliases,original_language,region,genres,
                    synopsis,cover_url,content_fingerprint,created_by)
                   VALUES (%s,%s,%s,'[]','en','US','[\"drama\"]','','',%s,%s)""",
                (cls.tenant_id, "Acceptance Drama", "acceptance drama", (cls.prefix + "0" * 64)[:64], cls.owner_username),
            )
            cls.drama_id = int(cur.lastrowid)
            cls.material_ids = []
            cls.version_ids = []
            for index in range(1, 53):
                cur.execute(
                    """INSERT INTO material_masters
                       (tenant_id,drama_id,name,material_type,description,tags,status,
                        latest_version_number,created_by)
                       VALUES (%s,%s,%s,'video','','[]','active',%s,%s)""",
                    (cls.tenant_id, cls.drama_id, f"Acceptance material {index:02d}", 0 if index == 4 else 1, cls.owner_username),
                )
                material_id = int(cur.lastrowid)
                cls.material_ids.append(material_id)
                version_id = None
                if index != 4:
                    cur.execute(
                        """INSERT INTO material_versions
                           (tenant_id,material_id,version_number,source_filename,file_extension,mime_type,
                            size_bytes,checksum_sha256,width,height,duration_ms,storage_backend,storage_key,
                            upload_status,metadata_json,notes,created_by)
                           VALUES (%s,%s,1,%s,'mp4','video/mp4',1024,%s,1080,1920,30000,
                                   'local',%s,%s,'{}','acceptance',%s)""",
                        (cls.tenant_id, material_id, f"acceptance-{index:02d}.mp4", f"{index:064x}",
                         f"acceptance/{index:02d}.mp4", "pending_upload" if index == 3 else "uploaded", cls.owner_username),
                    )
                    version_id = int(cur.lastrowid)
                cls.version_ids.append(version_id)
                cur.execute(
                    """INSERT INTO app_application_materials
                       (tenant_id,application_id,material_id,selected_version_id,selection_mode,status,notes,created_by)
                       VALUES (%s,%s,%s,%s,'latest','selected','acceptance',%s)""",
                    (cls.tenant_id, cls.application_id, material_id, None, cls.owner_username),
                )
            for index, asset, account_suffix in (
                (1, "video-complete", "-account"), (5, "video-no-data", "-account"),
                (6, "video-delayed", "-account"), (7, "video-partial-a", "-account"),
                (7, "video-partial-b", "-account-b"),
            ):
                cur.execute(
                    """INSERT INTO app_platform_material_mappings
                       (tenant_id,application_id,platform,account_id,material_id,version_id,
                        platform_asset_id,upload_status,created_by)
                       VALUES (%s,%s,'tiktok',%s,%s,%s,%s,'uploaded',%s)""",
                    (cls.tenant_id, cls.application_id, cls.prefix + account_suffix,
                     cls.material_ids[index - 1], cls.version_ids[index - 1], asset, cls.owner_username),
                )
            conn.commit()

        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO biz_ad_accounts
                   (platform,account_id,account_name,currency,timezone,status,access_token,app_id,
                    app_secret,is_default,tenant_id,application_id)
                   VALUES ('tiktok',%s,'Acceptance Account','USD','Asia/Shanghai','ACTIVE',NULL,'','',0,%s,%s)""",
                (cls.prefix + "-account", cls.tenant_id, cls.application_id),
            )
            cur.execute(
                """INSERT INTO biz_ad_accounts
                   (platform,account_id,account_name,currency,timezone,status,access_token,app_id,
                    app_secret,is_default,tenant_id,application_id)
                   VALUES ('tiktok',%s,'Acceptance Account B','USD','Asia/Shanghai','ACTIVE',NULL,'','',0,%s,%s)""",
                (cls.prefix + "-account-b", cls.tenant_id, cls.application_id),
            )
            facts = [
                ("2026-10-21", "accept-complete", "video-complete", "10.0000", "20.0000"),
                ("2026-10-20", "accept-delayed", "video-delayed", "4.0000", "4.0000"),
                ("2026-10-21", "accept-partial", "video-partial-a", "3.0000", "6.0000"),
                ("2026-10-21", "accept-unmapped", "video-unknown", "7.0000", "0.0000"),
            ]
            for day, ad_id, video_id, spend, revenue in facts:
                cur.execute(
                    """INSERT INTO biz_attribution_ad_daily
                       (ds_la,ds_account_local,account_timezone,timezone_source,platform,account_id,
                        account_name,ad_id,ad_name,video_id,spend,impressions,clicks,conversion,install,
                        total_recharge_amount,upstream_updated_at)
                       VALUES (%s,%s,'Asia/Shanghai','account_dim','tiktok',%s,'Acceptance Account',
                               %s,%s,%s,%s,100,10,2,1,%s,'2026-10-21 06:00:00')""",
                    (day, day, cls.prefix + "-account", cls.prefix + "-" + ad_id,
                     ad_id, video_id, spend, revenue),
                )
            conn.commit()

    @classmethod
    def _fingerprint(cls):
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c,COALESCE(SUM(id),0) AS s FROM material_masters WHERE tenant_id=%s", (cls.tenant_id,))
            material = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c,COALESCE(SUM(id),0) AS s FROM app_platform_material_mappings WHERE tenant_id=%s", (cls.tenant_id,))
            mappings = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c FROM app_oplog WHERE tenant_id=%s", (cls.tenant_id,))
            oplog = cur.fetchone()
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c,COALESCE(SUM(id),0) AS s FROM biz_attribution_ad_daily WHERE account_id=%s", (cls.prefix + "-account",))
            facts = cur.fetchone()
        return material, mappings, oplog, facts

    def test_real_http_contract_permissions_isolation_pagination_and_zero_write(self):
        before = self._fingerprint()
        path = "/api/asset-analysis/report?date_from=2026-10-20&date_to=2026-10-21"

        self.assertEqual(request("GET", path)[0], 401)
        self.assertEqual(request("GET", "/api/asset-analysis/report", headers=self.owner_headers)[0], 422)
        self.assertEqual(request("GET", path + "&page=0", headers=self.owner_headers)[0], 422)
        self.assertEqual(request("GET", path.replace("2026-10-20", "2026-10-22"), headers=self.owner_headers)[0], 422)
        self.assertEqual(request("GET", path, headers=self.outsider_headers)[0], 403)

        status, report = request("GET", path, headers=self.owner_headers)
        self.assertEqual(status, 200)
        self.assertEqual(report["contract"], "asset_analysis.v1")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["scope"], {"tenant_id": self.tenant_id, "application_id": self.application_id})
        self.assertEqual(report["total"], 52)
        self.assertEqual(len(report["items"]), 50)
        self.assertEqual(report["coverage"]["fact_rows_total"], 4)
        self.assertEqual(report["coverage"]["unmapped_fact_rows"], 1)
        states = report["coverage"]["states"]
        for expected in ("complete", "delayed", "partial", "unmapped", "not_uploaded", "missing_version", "no_platform_data"):
            self.assertIn(expected, states)

        by_name = {row["name"]: row for row in report["items"]}
        complete = by_name["Acceptance material 01"]
        self.assertEqual(complete["coverage_status"], "complete")
        self.assertEqual(complete["metrics"]["roi"], "2.000000")
        self.assertEqual(by_name["Acceptance material 02"]["coverage_status"], "unmapped")
        self.assertIsNone(by_name["Acceptance material 02"]["metrics"]["spend"])
        self.assertEqual(by_name["Acceptance material 03"]["coverage_status"], "not_uploaded")
        self.assertEqual(by_name["Acceptance material 04"]["coverage_status"], "missing_version")
        self.assertEqual(by_name["Acceptance material 05"]["coverage_status"], "no_platform_data")
        self.assertEqual(by_name["Acceptance material 06"]["coverage_status"], "delayed")
        self.assertEqual(by_name["Acceptance material 07"]["coverage_status"], "partial")

        status, second = request("GET", path + "&page=2", headers=self.owner_headers)
        self.assertEqual((status, len(second["items"]), second["page"]), (200, 2, 2))
        status, viewer = request("GET", path + "&query=material+01", headers=self.viewer_headers)
        self.assertEqual((status, viewer["total"]), (200, 1))
        status, drama = request("GET", path + "&dimension=drama", headers=self.viewer_headers)
        self.assertEqual((status, drama["dimension"], drama["total"]), (200, "drama", 1))
        self.assertEqual(drama["items"][0]["coverage_status"], "partial")

        status, other = request("GET", path, headers=self.other_app_headers)
        self.assertEqual((status, other["total"], other["scope"]["application_id"]), (200, 0, self.other_application_id))
        status, foreign = request("GET", path, headers=self.foreign_headers)
        self.assertEqual((status, foreign["total"]), (200, 0))
        self.assertEqual(request("GET", path, headers=self.owner_headers), (200, report))
        self.assertEqual(self._fingerprint(), before)

    def test_z_dependency_failure_is_visible_and_recovers(self):
        path = "/api/asset-analysis/report?date_from=2026-10-20&date_to=2026-10-21"
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute("RENAME TABLE biz_attribution_ad_daily TO biz_attribution_ad_daily_acceptance_hold")
            conn.commit()
        try:
            status, failure = request("GET", path, headers=self.owner_headers)
            self.assertEqual(status, 500)
            self.assertIn("message", failure)
        finally:
            with get_biz_conn() as conn:
                cur = conn.cursor()
                cur.execute("RENAME TABLE biz_attribution_ad_daily_acceptance_hold TO biz_attribution_ad_daily")
                conn.commit()
        status, recovered = request("GET", path, headers=self.owner_headers)
        self.assertEqual(status, 200)
        self.assertEqual(recovered["total"], 52)


if __name__ == "__main__":
    unittest.main()
