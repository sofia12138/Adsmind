"""Create tenant material masters/versions and application selection references."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0006_material_catalog"
DESCRIPTION = "Create tenant material masters and versions with application references"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0005_"


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError("0006_material_catalog requires the applied 0005 migration")
        cur.execute("""CREATE TABLE material_masters (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            drama_id BIGINT DEFAULT NULL,
            name VARCHAR(255) NOT NULL,
            material_type VARCHAR(20) NOT NULL,
            description TEXT DEFAULT NULL,
            tags JSON NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            latest_version_number INT NOT NULL DEFAULT 0,
            revision INT NOT NULL DEFAULT 1,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_material_master_scope_id (id, tenant_id),
            KEY idx_material_master_list (tenant_id, status, updated_at),
            KEY idx_material_master_drama (tenant_id, drama_id),
            CONSTRAINT fk_material_master_tenant FOREIGN KEY (tenant_id)
              REFERENCES app_tenants (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_material_master_drama_scope FOREIGN KEY (drama_id, tenant_id)
              REFERENCES drama_masters (id, tenant_id) ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE material_versions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            material_id BIGINT NOT NULL,
            version_number INT NOT NULL,
            source_filename VARCHAR(512) NOT NULL,
            file_extension VARCHAR(32) NOT NULL DEFAULT '',
            mime_type VARCHAR(127) NOT NULL,
            size_bytes BIGINT UNSIGNED NOT NULL,
            checksum_sha256 CHAR(64) DEFAULT NULL,
            width INT UNSIGNED DEFAULT NULL,
            height INT UNSIGNED DEFAULT NULL,
            duration_ms BIGINT UNSIGNED DEFAULT NULL,
            storage_backend VARCHAR(32) NOT NULL DEFAULT 'unconfigured',
            storage_key VARCHAR(1024) DEFAULT NULL,
            upload_status VARCHAR(24) NOT NULL DEFAULT 'pending_upload',
            upload_error VARCHAR(1000) DEFAULT NULL,
            metadata_json JSON NOT NULL,
            notes VARCHAR(1000) NOT NULL DEFAULT '',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_material_version_number (tenant_id, material_id, version_number),
            UNIQUE KEY uq_material_version_scope_id (id, tenant_id, material_id),
            KEY idx_material_version_list (tenant_id, material_id, created_at),
            CONSTRAINT fk_material_version_master_scope FOREIGN KEY (material_id, tenant_id)
              REFERENCES material_masters (id, tenant_id) ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_application_materials (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            material_id BIGINT NOT NULL,
            selected_version_id BIGINT DEFAULT NULL,
            selection_mode VARCHAR(16) NOT NULL DEFAULT 'latest',
            status VARCHAR(20) NOT NULL DEFAULT 'selected',
            notes VARCHAR(1000) NOT NULL DEFAULT '',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_application_material (tenant_id, application_id, material_id),
            KEY idx_application_material_scope (tenant_id, application_id, id),
            KEY idx_application_material_version (selected_version_id, tenant_id, material_id),
            CONSTRAINT fk_application_material_application_scope
              FOREIGN KEY (application_id, tenant_id) REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_application_material_master_scope
              FOREIGN KEY (material_id, tenant_id) REFERENCES material_masters (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_application_material_version_scope
              FOREIGN KEY (selected_version_id, tenant_id, material_id)
              REFERENCES material_versions (id, tenant_id, material_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DROP TABLE app_application_materials")
        cur.execute("DROP TABLE material_versions")
        cur.execute("DROP TABLE material_masters")
        conn.commit()
