"""Add the application-owned configuration and execution repositories."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0003_application_resources"
DESCRIPTION = "Create application-scoped account/creative groups, naming rules and execution records"
REVERSIBLE = True


_TABLES = (
    "app_account_groups",
    "app_creative_groups",
    "app_naming_rules",
    "app_execution_records",
)


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE app_account_groups (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            name VARCHAR(160) NOT NULL,
            account_refs JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_account_group_name (tenant_id, application_id, name),
            KEY idx_account_group_scope (tenant_id, application_id, id),
            CONSTRAINT fk_account_group_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_creative_groups (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            name VARCHAR(160) NOT NULL,
            asset_refs JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_creative_group_name (tenant_id, application_id, name),
            KEY idx_creative_group_scope (tenant_id, application_id, id),
            CONSTRAINT fk_creative_group_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_naming_rules (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            name VARCHAR(160) NOT NULL,
            rule JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_naming_rule_name (tenant_id, application_id, name),
            KEY idx_naming_rule_scope (tenant_id, application_id, id),
            CONSTRAINT fk_naming_rule_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE app_execution_records (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            operation VARCHAR(100) NOT NULL,
            target_type VARCHAR(64) NOT NULL DEFAULT '',
            target_id VARCHAR(128) NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            request_payload JSON DEFAULT NULL,
            result JSON DEFAULT NULL,
            error_message TEXT DEFAULT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME DEFAULT NULL,
            KEY idx_execution_scope (tenant_id, application_id, created_at),
            KEY idx_execution_target (tenant_id, application_id, target_type, target_id),
            CONSTRAINT fk_execution_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        for table in reversed(_TABLES):
            cur.execute(f"DROP TABLE {table}")
        conn.commit()
