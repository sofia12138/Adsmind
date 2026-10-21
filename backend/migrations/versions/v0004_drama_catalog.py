"""Create tenant-owned drama masters and application-owned references."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0004_drama_catalog"
DESCRIPTION = "Create tenant drama masters and application drama references"
REVERSIBLE = True


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE drama_masters (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            title VARCHAR(255) NOT NULL,
            normalized_title VARCHAR(255) NOT NULL,
            aliases JSON NOT NULL,
            original_language VARCHAR(32) NOT NULL DEFAULT '',
            region VARCHAR(64) NOT NULL DEFAULT '',
            genres JSON NOT NULL,
            synopsis TEXT DEFAULT NULL,
            cover_url VARCHAR(1024) NOT NULL DEFAULT '',
            content_fingerprint CHAR(64) NOT NULL,
            revision INT NOT NULL DEFAULT 1,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_drama_master_title (tenant_id, normalized_title),
            UNIQUE KEY uq_drama_master_fingerprint (tenant_id, content_fingerprint),
            UNIQUE KEY uq_drama_master_scope_id (id, tenant_id),
            KEY idx_drama_master_search (tenant_id, title),
            CONSTRAINT fk_drama_master_tenant
              FOREIGN KEY (tenant_id) REFERENCES app_tenants (id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_application_dramas (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            drama_id BIGINT NOT NULL,
            display_title VARCHAR(255) NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            notes TEXT DEFAULT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_application_drama (tenant_id, application_id, drama_id),
            KEY idx_application_drama_scope (tenant_id, application_id, id),
            KEY idx_application_drama_master (tenant_id, drama_id),
            CONSTRAINT fk_application_drama_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_application_drama_master_scope
              FOREIGN KEY (drama_id, tenant_id)
              REFERENCES drama_masters (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DROP TABLE app_application_dramas")
        cur.execute("DROP TABLE drama_masters")
        conn.commit()
