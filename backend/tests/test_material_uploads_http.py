"""Opt-in real HTTP acceptance against a running local AdsMind backend."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import urllib.error
import urllib.request
import uuid

from auth import create_token
from db import get_app_conn
from repositories import application_repository, tenant_member_repository, user_repository


BASE = os.getenv("ADSMIND_HTTP_BASE_URL", "")


def request(method: str, path: str, body=None, headers=None, raw: bytes | None = None):
    payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    all_headers = {"Content-Type": "application/octet-stream" if raw is not None else "application/json", **(headers or {})}
    call = urllib.request.Request(BASE + path, data=payload, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(call, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@unittest.skipUnless(BASE, "requires a running local HTTP server")
class MaterialUploadHTTPAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = "upload-http-" + uuid.uuid4().hex[:10]
        status, owner = request("POST", "/api/auth/register", {
            "email": cls.prefix + "@example.test", "password": "Acceptance-1234",
            "company_name": "Upload HTTP Acceptance", "plan_id": "pro",
        })
        assert status == 200, owner
        cls.tenant_id = owner["tenant"]["id"]
        cls.application_id = owner["application"]["id"]
        cls.headers = {"Authorization": "Bearer " + owner["token"], "X-Application-Id": str(cls.application_id)}

        cls.other_application_id = application_repository.create(cls.tenant_id, "Other upload app")["id"]
        cls.other_app_headers = {**cls.headers, "X-Application-Id": str(cls.other_application_id)}

        limited = user_repository.create(username=cls.prefix + "-viewer", password_hash="unused", role="viewer", display_name="Viewer", assigned_accounts=[])
        tenant_member_repository.ensure_member(cls.tenant_id, limited["id"], "member")
        application_repository.add_member(cls.application_id, limited["id"], "viewer")
        cls.viewer_headers = {
            "Authorization": "Bearer " + create_token(limited["username"], "viewer", tenant_id=cls.tenant_id),
            "X-Application-Id": str(cls.application_id),
        }

        status, foreign = request("POST", "/api/auth/register", {
            "email": cls.prefix + "-foreign@example.test", "password": "Acceptance-1234",
            "company_name": "Foreign Upload Acceptance", "plan_id": "pro",
        })
        assert status == 200, foreign
        cls.foreign_headers = {"Authorization": "Bearer " + foreign["token"], "X-Application-Id": str(foreign["application"]["id"])}

    def test_real_http_flow_permissions_scopes_idempotency_and_database_readback(self):
        status, _ = request("GET", "/api/material-uploads")
        self.assertEqual(status, 401)

        status, master = request("POST", "/api/material-catalog/masters", {
            "name": "HTTP upload proof", "material_type": "image", "description": "acceptance",
            "tags": ["http"], "status": "active",
        }, self.headers)
        self.assertEqual(status, 201)

        status, invalid = request("POST", f"/api/material-catalog/masters/{master['id']}/versions", {
            "source_filename": "proof.png", "mime_type": "image/png", "size_bytes": 12,
            "checksum_sha256": "invalid", "notes": "",
        }, self.headers)
        self.assertEqual(status, 422)
        self.assertIsInstance(invalid["detail"], list)

        content = b"\x89PNG\r\n\x1a\n" + b"real-http-content"
        checksum = hashlib.sha256(content).hexdigest()
        status, version = request("POST", f"/api/material-catalog/masters/{master['id']}/versions", {
            "source_filename": "proof.png", "mime_type": "image/png", "size_bytes": len(content),
            "checksum_sha256": checksum, "notes": "real HTTP acceptance",
        }, self.headers)
        self.assertEqual(status, 201)
        self.assertEqual(version["upload_status"], "pending_upload")

        prepare_body = {"material_id": master["id"], "version_id": version["id"], "idempotency_key": "http-acceptance-proof", "mode": "direct"}
        status, upload = request("POST", "/api/material-uploads/prepare", prepare_body, self.headers)
        self.assertEqual(status, 201)
        self.assertEqual(upload["status"], "prepared")
        self.assertNotIn("storage_key", upload)

        status, repeated_prepare = request("POST", "/api/material-uploads/prepare", prepare_body, self.headers)
        self.assertEqual(status, 201)
        self.assertEqual(repeated_prepare["id"], upload["id"])

        status, _ = request("POST", "/api/material-uploads/prepare", {**prepare_body, "idempotency_key": "bad key"}, self.headers)
        self.assertEqual(status, 422)
        status, _ = request("POST", "/api/material-uploads/prepare", prepare_body, self.viewer_headers)
        self.assertEqual(status, 403)

        status, _ = request("GET", f"/api/material-uploads/{upload['id']}", headers=self.other_app_headers)
        self.assertEqual(status, 404)
        status, _ = request("GET", f"/api/material-uploads/{upload['id']}", headers=self.foreign_headers)
        self.assertEqual(status, 404)

        status, uploading = request("PUT", upload["upload"]["direct_url"], headers=self.headers, raw=content)
        self.assertEqual(status, 200)
        self.assertEqual(uploading["status"], "uploading")
        status, completed = request("POST", upload["upload"]["complete_url"], {"idempotency_key": "http-acceptance-proof"}, self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "uploaded")
        self.assertEqual(completed["progress"], 100)
        status, completed_again = request("POST", upload["upload"]["complete_url"], {"idempotency_key": "http-acceptance-proof"}, self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(completed_again["id"], upload["id"])

        status, refreshed = request("GET", f"/api/material-catalog/masters/{master['id']}", headers=self.headers)
        self.assertEqual(status, 200)
        refreshed_version = next(row for row in refreshed["versions"] if row["id"] == version["id"])
        self.assertEqual(refreshed_version["upload_status"], "uploaded")
        self.assertEqual(refreshed_version["checksum_sha256"], checksum)

        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status,verified_checksum_sha256,tenant_id,application_id FROM app_material_uploads WHERE id=%s", (upload["id"],))
            persisted = cur.fetchone()
            cur.execute("SELECT event_type,to_status FROM app_material_upload_audit WHERE upload_id=%s ORDER BY id", (upload["id"],))
            audit = cur.fetchall()
        self.assertEqual(persisted, {"status": "uploaded", "verified_checksum_sha256": checksum, "tenant_id": self.tenant_id, "application_id": self.application_id})
        self.assertEqual([row["event_type"] for row in audit], ["prepared", "bytes_received", "verified"])

        bad_content = b"\x89PNG\r\n\x1a\n" + b"wrong-content"
        status, bad_version = request("POST", f"/api/material-catalog/masters/{master['id']}/versions", {
            "source_filename": "bad.png", "mime_type": "image/png", "size_bytes": len(bad_content),
            "checksum_sha256": "f" * 64, "notes": "verification failure",
        }, self.headers)
        self.assertEqual(status, 201)
        status, bad_upload = request("POST", "/api/material-uploads/prepare", {
            "material_id": master["id"], "version_id": bad_version["id"], "idempotency_key": "http-failure-proof", "mode": "direct",
        }, self.headers)
        self.assertEqual(status, 201)
        self.assertEqual(request("PUT", bad_upload["upload"]["direct_url"], headers=self.headers, raw=bad_content)[0], 200)
        status, failure = request("POST", bad_upload["upload"]["complete_url"], {"idempotency_key": "http-failure-proof"}, self.headers)
        self.assertEqual(status, 422)
        self.assertIn("SHA-256", failure["detail"])
        status, bad_refreshed = request("GET", f"/api/material-catalog/masters/{master['id']}", headers=self.headers)
        self.assertEqual(status, 200)
        failed_version = next(row for row in bad_refreshed["versions"] if row["id"] == bad_version["id"])
        self.assertEqual(failed_version["upload_status"], "failed")


if __name__ == "__main__":
    unittest.main()
