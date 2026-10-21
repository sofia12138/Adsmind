"""Add application-scoped, preparation-only ad creation drafts."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0008_ad_creation_drafts"
DESCRIPTION = "Add internal ad creation drafts and immutable execution snapshots"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0007_"
PANEL = ("ad_creation_drafts", "应用广告草稿", "投放管理", "/ads/app-drafts", 23)
ROLE_KEYS = ("super_admin", "admin", "optimizer")
REQUIRED_COLUMNS = {
    "id", "tenant_id", "application_id", "status", "revision",
    "account_group_id", "naming_rule_id", "creative_group_id",
    "resolved_accounts", "name_previews", "creative_snapshot",
    "blocking_reasons", "execution_snapshot", "execution_snapshot_hash",
}
REQUIRED_CONSTRAINTS = {
    "fk_ad_creation_application_scope",
    "fk_ad_creation_account_group_scope",
    "fk_ad_creation_naming_rule_scope",
    "fk_ad_creation_creative_group_scope",
}


def _index_exists(cur, table: str, index: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1""",
        (table, index),
    )
    return bool(cur.fetchone())


def _assert_compatible(cur) -> None:
    cur.execute(
        """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_ad_creation_drafts'"""
    )
    columns = {str(row["COLUMN_NAME"]) for row in (cur.fetchall() or [])}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "app_ad_creation_drafts 已存在但结构不兼容，缺少列："
            + ",".join(sorted(missing))
        )
    cur.execute(
        """SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA=DATABASE()
             AND TABLE_NAME='app_ad_creation_drafts'"""
    )
    constraints = {str(row["CONSTRAINT_NAME"]) for row in (cur.fetchall() or [])}
    missing_constraints = REQUIRED_CONSTRAINTS - constraints
    if missing_constraints:
        raise RuntimeError(
            "app_ad_creation_drafts 已存在但缺少作用域外键："
            + ",".join(sorted(missing_constraints))
        )


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError("0008_ad_creation_drafts requires the applied 0007 migration")

        for table, index in (
            ("app_account_groups", "uq_account_group_scope_id"),
            ("app_naming_rules", "uq_naming_rule_scope_id"),
        ):
            if not _index_exists(cur, table, index):
                cur.execute(
                    f"ALTER TABLE {table} ADD UNIQUE KEY {index} (id, tenant_id, application_id)"
                )

        cur.execute("""CREATE TABLE IF NOT EXISTS app_ad_creation_drafts (
            id CHAR(36) PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            created_by VARCHAR(100) NOT NULL,
            request_key CHAR(36) NOT NULL,
            title VARCHAR(160) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
            revision INT UNSIGNED NOT NULL DEFAULT 1,
            account_group_id BIGINT NOT NULL,
            naming_rule_id BIGINT NOT NULL,
            creative_group_id BIGINT NOT NULL,
            naming_values JSON NOT NULL,
            resolved_accounts JSON NOT NULL,
            name_previews JSON NOT NULL,
            creative_snapshot JSON NOT NULL,
            blocking_reasons JSON NOT NULL,
            execution_snapshot JSON DEFAULT NULL,
            execution_snapshot_hash CHAR(64) DEFAULT NULL,
            ready_at DATETIME DEFAULT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_ad_creation_request
              (tenant_id, application_id, created_by, request_key),
            UNIQUE KEY uq_ad_creation_scope_id (id, tenant_id, application_id),
            KEY idx_ad_creation_scope
              (tenant_id, application_id, updated_at, id),
            KEY idx_ad_creation_account_group
              (account_group_id, tenant_id, application_id),
            KEY idx_ad_creation_naming_rule
              (naming_rule_id, tenant_id, application_id),
            KEY idx_ad_creation_creative_group
              (creative_group_id, tenant_id, application_id),
            CONSTRAINT fk_ad_creation_application_scope
              FOREIGN KEY (application_id, tenant_id)
              REFERENCES app_applications (id, tenant_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_ad_creation_account_group_scope
              FOREIGN KEY (account_group_id, tenant_id, application_id)
              REFERENCES app_account_groups (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_ad_creation_naming_rule_scope
              FOREIGN KEY (naming_rule_id, tenant_id, application_id)
              REFERENCES app_naming_rules (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_ad_creation_creative_group_scope
              FOREIGN KEY (creative_group_id, tenant_id, application_id)
              REFERENCES app_creative_groups (id, tenant_id, application_id)
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
                """INSERT IGNORE INTO role_panel_permissions
                   (role_key, panel_key, can_view) VALUES (%s,%s,1)""",
                (role, PANEL[0]),
            )
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM role_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM panel_definitions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DROP TABLE IF EXISTS app_ad_creation_drafts")
        for table, index in (
            ("app_account_groups", "uq_account_group_scope_id"),
            ("app_naming_rules", "uq_naming_rule_scope_id"),
        ):
            if _index_exists(cur, table, index):
                cur.execute(f"ALTER TABLE {table} DROP INDEX {index}")
        conn.commit()
