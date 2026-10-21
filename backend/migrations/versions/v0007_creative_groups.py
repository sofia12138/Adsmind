"""Add application creative groups backed by material-catalog references."""
from __future__ import annotations

import json

from db import get_app_conn


VERSION = "0007_creative_groups"
DESCRIPTION = "Add material-backed creative groups and their management panel"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0006_"

PANEL = ("creative_groups", "创意组", "素材中心", "/creative-groups", 34)
ROLE_KEYS = ("super_admin", "admin", "optimizer", "designer")

_REQUIRED_COLUMNS = {
    "id", "tenant_id", "application_id", "creative_group_id", "material_id",
    "selection_mode", "selected_version_id", "position",
}
_REQUIRED_CONSTRAINTS = {
    "fk_creative_group_material_group_scope",
    "fk_creative_group_material_application_reference",
    "fk_creative_group_material_version_scope",
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
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_creative_group_materials'"""
    )
    columns = {str(row["COLUMN_NAME"]) for row in (cur.fetchall() or [])}
    missing = _REQUIRED_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "app_creative_group_materials 已存在但结构不兼容，缺少列："
            + ",".join(sorted(missing))
        )
    cur.execute(
        """SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA=DATABASE()
             AND TABLE_NAME='app_creative_group_materials'"""
    )
    constraints = {str(row["CONSTRAINT_NAME"]) for row in (cur.fetchall() or [])}
    missing_constraints = _REQUIRED_CONSTRAINTS - constraints
    if missing_constraints:
        raise RuntimeError(
            "app_creative_group_materials 已存在但缺少作用域外键："
            + ",".join(sorted(missing_constraints))
        )


def _backfill_contract_refs(cur) -> None:
    """Restore valid 0007 refs retained in asset_refs after a downgrade."""
    cur.execute("SELECT id, tenant_id, application_id, asset_refs FROM app_creative_groups")
    for group in cur.fetchall() or []:
        raw = group.get("asset_refs")
        try:
            refs = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(refs, list):
            continue
        for position, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            mode = ref.get("selection_mode")
            material_id = ref.get("material_id")
            version_id = ref.get("selected_version_id")
            if mode not in ("latest", "pinned") or not isinstance(material_id, int):
                continue
            if (mode == "latest" and version_id is not None) or (
                mode == "pinned" and not isinstance(version_id, int)
            ):
                continue
            cur.execute(
                """INSERT IGNORE INTO app_creative_group_materials
                   (tenant_id, application_id, creative_group_id, material_id,
                    selection_mode, selected_version_id, position)
                   SELECT g.tenant_id, g.application_id, g.id, r.material_id,
                          %s, v.id, %s
                     FROM app_creative_groups g
                     JOIN app_application_materials r
                       ON r.tenant_id=g.tenant_id AND r.application_id=g.application_id
                      AND r.material_id=%s
                     LEFT JOIN material_versions v
                       ON v.id=%s AND v.tenant_id=r.tenant_id AND v.material_id=r.material_id
                    WHERE g.id=%s AND g.tenant_id=%s AND g.application_id=%s
                      AND (%s IS NULL OR v.id IS NOT NULL)""",
                (mode, position, material_id, version_id, group["id"],
                 group["tenant_id"], group["application_id"], version_id),
            )


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError("0007_creative_groups requires the applied 0006 migration")

        # MySQL requires a referenced composite key whose first columns match
        # the foreign key.  This also documents the complete ownership key.
        if not _index_exists(cur, "app_creative_groups", "uq_creative_group_scope_id"):
            cur.execute(
                "ALTER TABLE app_creative_groups "
                "ADD UNIQUE KEY uq_creative_group_scope_id (id, tenant_id, application_id)"
            )
        cur.execute("""CREATE TABLE IF NOT EXISTS app_creative_group_materials (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL,
            creative_group_id BIGINT NOT NULL,
            material_id BIGINT NOT NULL,
            selection_mode VARCHAR(16) NOT NULL DEFAULT 'latest',
            selected_version_id BIGINT DEFAULT NULL,
            position INT UNSIGNED NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_creative_group_material
              (tenant_id, application_id, creative_group_id, material_id),
            KEY idx_creative_group_material_list
              (tenant_id, application_id, creative_group_id, position, id),
            KEY idx_creative_group_material_version
              (selected_version_id, tenant_id, material_id),
            CONSTRAINT fk_creative_group_material_group_scope
              FOREIGN KEY (creative_group_id, tenant_id, application_id)
              REFERENCES app_creative_groups (id, tenant_id, application_id)
              ON UPDATE RESTRICT ON DELETE CASCADE,
            CONSTRAINT fk_creative_group_material_application_reference
              FOREIGN KEY (tenant_id, application_id, material_id)
              REFERENCES app_application_materials (tenant_id, application_id, material_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT,
            CONSTRAINT fk_creative_group_material_version_scope
              FOREIGN KEY (selected_version_id, tenant_id, material_id)
              REFERENCES material_versions (id, tenant_id, material_id)
              ON UPDATE RESTRICT ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        _assert_compatible(cur)
        _backfill_contract_refs(cur)

        cur.execute(
            """INSERT INTO panel_definitions
               (panel_key, panel_name, panel_group, route_path, sort_order)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE panel_name=VALUES(panel_name),
                 panel_group=VALUES(panel_group), route_path=VALUES(route_path),
                 sort_order=VALUES(sort_order), is_enabled=1""",
            PANEL,
        )
        for role in ROLE_KEYS:
            cur.execute(
                """INSERT IGNORE INTO role_panel_permissions
                   (role_key, panel_key, can_view) VALUES (%s, %s, 1)""",
                (role, PANEL[0]),
            )
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM role_panel_permissions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DELETE FROM panel_definitions WHERE panel_key=%s", (PANEL[0],))
        cur.execute("DROP TABLE app_creative_group_materials")
        cur.execute(
            "ALTER TABLE app_creative_groups DROP INDEX uq_creative_group_scope_id"
        )
        conn.commit()
