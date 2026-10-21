"""Add application-scoped material upload sessions, parts and audit."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0011_material_uploads"
DESCRIPTION = "Add verified, resumable material upload sessions and storage audit"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0010_"


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError("0011_material_uploads requires the applied 0010 migration")
        cur.execute("""CREATE TABLE app_material_uploads (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            material_id BIGINT NOT NULL,
            version_id BIGINT NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            upload_mode VARCHAR(16) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'prepared',
            storage_backend VARCHAR(32) NOT NULL,
            storage_key VARCHAR(1024) NOT NULL,
            expected_size_bytes BIGINT UNSIGNED NOT NULL,
            expected_mime_type VARCHAR(127) NOT NULL,
            expected_checksum_sha256 CHAR(64) NOT NULL,
            received_size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
            verified_checksum_sha256 CHAR(64) DEFAULT NULL,
            part_size_bytes INT UNSIGNED DEFAULT NULL,
            part_count INT UNSIGNED DEFAULT NULL,
            attempt_count INT UNSIGNED NOT NULL DEFAULT 1,
            error_code VARCHAR(80) DEFAULT NULL,
            error_message VARCHAR(1000) DEFAULT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            expires_at DATETIME NOT NULL,
            completed_at DATETIME DEFAULT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_material_upload_idempotency (tenant_id, application_id, idempotency_key),
            UNIQUE KEY uq_material_upload_scope_id (id, tenant_id, application_id),
            KEY idx_material_upload_version (tenant_id, application_id, material_id, version_id, created_at),
            KEY idx_material_upload_status (tenant_id, application_id, status, expires_at),
            CONSTRAINT fk_material_upload_application_scope
              FOREIGN KEY (application_id, tenant_id) REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_material_upload_version_scope
              FOREIGN KEY (version_id, tenant_id, material_id) REFERENCES material_versions (id, tenant_id, material_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_material_upload_mode CHECK (upload_mode IN ('direct','multipart')),
            CONSTRAINT chk_material_upload_status CHECK (status IN ('prepared','uploading','verifying','uploaded','failed','expired'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_material_upload_parts (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            upload_id CHAR(36) NOT NULL,
            part_number INT UNSIGNED NOT NULL,
            size_bytes INT UNSIGNED NOT NULL DEFAULT 0,
            checksum_sha256 CHAR(64) DEFAULT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            uploaded_at DATETIME DEFAULT NULL,
            UNIQUE KEY uq_material_upload_part (tenant_id, application_id, upload_id, part_number),
            KEY idx_material_upload_part_scope (tenant_id, application_id, upload_id, status),
            CONSTRAINT fk_material_upload_part_scope
              FOREIGN KEY (upload_id, tenant_id, application_id) REFERENCES app_material_uploads (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_material_upload_part_status CHECK (status IN ('pending','uploaded','failed'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_material_upload_audit (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            upload_id CHAR(36) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            from_status VARCHAR(24) DEFAULT NULL,
            to_status VARCHAR(24) DEFAULT NULL,
            event_payload JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_material_upload_audit (tenant_id, application_id, upload_id, id),
            CONSTRAINT fk_material_upload_audit_scope
              FOREIGN KEY (upload_id, tenant_id, application_id) REFERENCES app_material_uploads (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS app_material_upload_audit")
        cur.execute("DROP TABLE IF EXISTS app_material_upload_parts")
        cur.execute("DROP TABLE IF EXISTS app_material_uploads")
        conn.commit()
