"""Add application-scoped platform mappings and immutable dry-run preflights."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0009_platform_preflight"
DESCRIPTION = "Add platform mappings, dry-run preflight records, idempotency and audit"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0008_"
PANEL = ("platform_preflight", "平台执行预检", "投放管理", "/ads/platform-preflight", 24)
ROLE_KEYS = ("super_admin", "admin", "optimizer")
TABLES = (
    "app_platform_preflight_audit",
    "app_platform_preflight_runs",
    "app_platform_material_mappings",
    "app_platform_account_mappings",
)
REQUIRED_COLUMNS = {
    "app_platform_account_mappings": {"tenant_id", "application_id", "platform", "account_id", "credential_external_id", "status"},
    "app_platform_material_mappings": {"tenant_id", "application_id", "platform", "account_id", "material_id", "version_id", "platform_asset_id", "upload_status"},
    "app_platform_preflight_runs": {"tenant_id", "application_id", "draft_id", "request_key", "snapshot_hash", "blocking_reasons", "dry_run_plan", "plan_hash", "execution_key", "dry_run", "external_write_authorized"},
    "app_platform_preflight_audit": {"tenant_id", "application_id", "run_id", "event_type", "event_payload"},
}


def _assert_compatible(cur) -> None:
    for table, required in REQUIRED_COLUMNS.items():
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
            (table,),
        )
        actual = {str(row["COLUMN_NAME"]) for row in (cur.fetchall() or [])}
        missing = required - actual
        if missing:
            raise RuntimeError(f"{table} 已存在但结构不兼容，缺少列：{','.join(sorted(missing))}")


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError("0009_platform_preflight requires the applied 0008 migration")

        cur.execute("""CREATE TABLE IF NOT EXISTS app_platform_account_mappings (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            platform VARCHAR(32) NOT NULL,
            account_id VARCHAR(128) NOT NULL,
            external_account_id VARCHAR(128) NOT NULL,
            credential_external_id VARCHAR(128) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_platform_account_mapping
              (tenant_id, application_id, platform, account_id),
            UNIQUE KEY uq_platform_account_mapping_scope_id
              (id, tenant_id, application_id),
            KEY idx_platform_account_mapping_scope
              (tenant_id, application_id, status, platform),
            CONSTRAINT fk_platform_account_mapping_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_platform_material_mappings (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            platform VARCHAR(32) NOT NULL,
            account_id VARCHAR(128) NOT NULL,
            material_id BIGINT NOT NULL,
            version_id BIGINT NOT NULL,
            platform_asset_id VARCHAR(255) NOT NULL,
            upload_status VARCHAR(24) NOT NULL DEFAULT 'pending_upload',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_platform_material_mapping
              (tenant_id, application_id, platform, account_id, material_id, version_id),
            UNIQUE KEY uq_platform_material_mapping_scope_id
              (id, tenant_id, application_id),
            KEY idx_platform_material_mapping_scope
              (tenant_id, application_id, platform, account_id, upload_status),
            CONSTRAINT fk_platform_material_mapping_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_platform_preflight_runs (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            draft_id CHAR(36) NOT NULL,
            request_key CHAR(36) NOT NULL,
            snapshot_hash CHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL,
            blocking_reasons JSON NOT NULL,
            dry_run_plan JSON NOT NULL,
            plan_hash CHAR(64) NOT NULL,
            execution_key CHAR(64) NOT NULL,
            dry_run TINYINT(1) NOT NULL DEFAULT 1,
            external_write_authorized TINYINT(1) NOT NULL DEFAULT 0,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_platform_preflight_request
              (tenant_id, application_id, request_key),
            UNIQUE KEY uq_platform_preflight_execution_key
              (tenant_id, application_id, execution_key),
            UNIQUE KEY uq_platform_preflight_scope_id
              (id, tenant_id, application_id),
            KEY idx_platform_preflight_draft
              (tenant_id, application_id, draft_id, created_at),
            CONSTRAINT fk_platform_preflight_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_platform_preflight_draft_scope
              FOREIGN KEY (draft_id, tenant_id, application_id)
              REFERENCES app_ad_creation_drafts (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_platform_preflight_dry_run CHECK (dry_run = 1),
            CONSTRAINT chk_platform_preflight_no_external_write
              CHECK (external_write_authorized = 0)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_platform_preflight_audit (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            run_id CHAR(36) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            event_payload JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_platform_preflight_audit
              (tenant_id, application_id, run_id, id),
            CONSTRAINT fk_platform_preflight_audit_run_scope
              FOREIGN KEY (run_id, tenant_id, application_id)
              REFERENCES app_platform_preflight_runs (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        _assert_compatible(cur)
        cur.execute(
            """INSERT INTO panel_definitions
               (panel_key, panel_name, panel_group, route_path, sort_order)
               VALUES (%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE panel_name=VALUES(panel_name),
                 panel_group=VALUES(panel_group), route_path=VALUES(route_path),
                 sort_order=VALUES(sort_order), is_enabled=1""",
            PANEL,
        )
        for role in ROLE_KEYS:
            cur.execute(
                "INSERT IGNORE INTO role_panel_permissions (role_key, panel_key, can_view) VALUES (%s,%s,1)",
                (role, PANEL[0]),
            )
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM role_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM panel_definitions WHERE panel_key=%s", (PANEL[0],))
        for table in TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
