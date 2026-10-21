"""Register account-group and naming-rule management panels."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0005_application_settings_panels"
DESCRIPTION = "Register account-group and naming-rule panels and default view permissions"
REVERSIBLE = True
REQUIRED_PREDECESSOR_PREFIX = "0004_"

PANELS = (
    ("account_groups", "账户组", "系统管理", "/settings/account-groups", 68),
    ("naming_rules", "命名规则", "系统管理", "/settings/naming-rules", 69),
)
ROLE_KEYS = ("super_admin", "admin", "optimizer")


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT version FROM app_schema_migrations WHERE version LIKE %s LIMIT 1",
            (f"{REQUIRED_PREDECESSOR_PREFIX}%",),
        )
        if not cur.fetchone():
            raise RuntimeError(
                "0005_application_settings_panels 依赖已整合并执行的 0004_* 迁移；"
                "当前分支仅可执行 migration plan"
            )
        for panel in PANELS:
            cur.execute(
                """INSERT INTO panel_definitions
                   (panel_key, panel_name, panel_group, route_path, sort_order)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE panel_name=VALUES(panel_name),
                     panel_group=VALUES(panel_group), route_path=VALUES(route_path),
                     sort_order=VALUES(sort_order), is_enabled=1""",
                panel,
            )
            for role in ROLE_KEYS:
                cur.execute(
                    """INSERT IGNORE INTO role_panel_permissions
                       (role_key, panel_key, can_view) VALUES (%s, %s, 1)""",
                    (role, panel[0]),
                )
        conn.commit()


def downgrade() -> None:
    keys = tuple(panel[0] for panel in PANELS)
    placeholders = ",".join(["%s"] * len(keys))
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM user_panel_permissions WHERE panel_key IN ({placeholders})", keys)
        cur.execute(f"DELETE FROM role_panel_permissions WHERE panel_key IN ({placeholders})", keys)
        cur.execute(f"DELETE FROM panel_definitions WHERE panel_key IN ({placeholders})", keys)
        conn.commit()
