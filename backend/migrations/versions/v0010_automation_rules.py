"""Add application-scoped, dry-run-only automation rule evaluation."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0010_automation_rules"
DESCRIPTION = "Add versioned automation rules, deterministic dry-run evaluations and append-only audit"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0009_"
PANEL = ("automation_rules", "自动化规则", "投放管理", "/ads/automation-rules", 25)
ROLE_KEYS = ("super_admin", "admin", "optimizer")
TABLES = (
    "app_automation_rule_audit",
    "app_automation_rule_recommendations",
    "app_automation_rule_evaluations",
    "app_automation_rule_versions",
    "app_automation_rules",
)
REQUIRED_COLUMNS = {
    "app_automation_rules": {"id", "tenant_id", "application_id", "name", "status", "current_version"},
    "app_automation_rule_versions": {"id", "tenant_id", "application_id", "rule_id", "version", "definition", "definition_hash"},
    "app_automation_rule_evaluations": {"id", "tenant_id", "application_id", "rule_id", "rule_version_id", "input_snapshot", "input_snapshot_hash", "evaluation_key", "blocking_reasons", "dry_run", "external_write_authorized"},
    "app_automation_rule_recommendations": {"id", "tenant_id", "application_id", "evaluation_id", "outcome", "reason_code", "reason_message"},
    "app_automation_rule_audit": {"id", "tenant_id", "application_id", "entity_type", "entity_id", "event_type", "event_payload"},
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
            raise RuntimeError("0010_automation_rules requires the applied 0009 migration")

        cur.execute("""CREATE TABLE IF NOT EXISTS app_automation_rules (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            name VARCHAR(160) NOT NULL,
            description VARCHAR(500) NOT NULL DEFAULT '',
            status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
            current_version INT UNSIGNED NOT NULL DEFAULT 1,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_automation_rule_name (tenant_id, application_id, name),
            UNIQUE KEY uq_automation_rule_scope_id (id, tenant_id, application_id),
            KEY idx_automation_rule_scope (tenant_id, application_id, status, updated_at),
            CONSTRAINT fk_automation_rule_application_scope
              FOREIGN KEY (application_id, tenant_id) REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_automation_rule_status CHECK (status IN ('ACTIVE','DISABLED'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_automation_rule_versions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            rule_id CHAR(36) NOT NULL,
            version INT UNSIGNED NOT NULL,
            definition JSON NOT NULL,
            definition_hash CHAR(64) NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_automation_rule_version (tenant_id, application_id, rule_id, version),
            UNIQUE KEY uq_automation_rule_version_scope_id (id, tenant_id, application_id),
            KEY idx_automation_rule_version_hash (tenant_id, application_id, definition_hash),
            CONSTRAINT fk_automation_rule_version_rule_scope
              FOREIGN KEY (rule_id, tenant_id, application_id)
              REFERENCES app_automation_rules (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_automation_rule_evaluations (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            rule_id CHAR(36) NOT NULL,
            rule_version_id BIGINT NOT NULL,
            input_snapshot JSON NOT NULL,
            input_snapshot_hash CHAR(64) NOT NULL,
            evaluation_key CHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL,
            blocking_reasons JSON NOT NULL,
            dry_run TINYINT(1) NOT NULL DEFAULT 1,
            external_write_authorized TINYINT(1) NOT NULL DEFAULT 0,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_automation_evaluation_key (tenant_id, application_id, evaluation_key),
            UNIQUE KEY uq_automation_evaluation_scope_id (id, tenant_id, application_id),
            KEY idx_automation_evaluation_rule (tenant_id, application_id, rule_id, created_at),
            CONSTRAINT fk_automation_evaluation_rule_scope
              FOREIGN KEY (rule_id, tenant_id, application_id)
              REFERENCES app_automation_rules (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_automation_evaluation_version_scope
              FOREIGN KEY (rule_version_id, tenant_id, application_id)
              REFERENCES app_automation_rule_versions (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_automation_evaluation_status CHECK (status IN ('CLEAR','REVIEW_REQUIRED','BLOCKED')),
            CONSTRAINT chk_automation_evaluation_dry_run CHECK (dry_run = 1),
            CONSTRAINT chk_automation_evaluation_no_external_write CHECK (external_write_authorized = 0)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_automation_rule_recommendations (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            evaluation_id CHAR(36) NOT NULL,
            outcome VARCHAR(32) NOT NULL DEFAULT 'review_required',
            reason_code VARCHAR(80) NOT NULL,
            reason_message VARCHAR(500) NOT NULL,
            evidence JSON NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_automation_recommendation (tenant_id, application_id, evaluation_id, reason_code),
            KEY idx_automation_recommendation_evaluation (tenant_id, application_id, evaluation_id, id),
            CONSTRAINT fk_automation_recommendation_evaluation_scope
              FOREIGN KEY (evaluation_id, tenant_id, application_id)
              REFERENCES app_automation_rule_evaluations (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT chk_automation_recommendation_outcome CHECK (outcome = 'review_required')
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("""CREATE TABLE IF NOT EXISTS app_automation_rule_audit (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            entity_type VARCHAR(32) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            event_payload JSON NOT NULL,
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_automation_rule_audit (tenant_id, application_id, entity_type, entity_id, id),
            CONSTRAINT fk_automation_audit_application_scope
              FOREIGN KEY (application_id, tenant_id) REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        _assert_compatible(cur)
        cur.execute(
            """INSERT INTO panel_definitions
               (panel_key, panel_name, panel_group, route_path, sort_order)
               VALUES (%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE panel_name=VALUES(panel_name), panel_group=VALUES(panel_group),
                 route_path=VALUES(route_path), sort_order=VALUES(sort_order), is_enabled=1""",
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
