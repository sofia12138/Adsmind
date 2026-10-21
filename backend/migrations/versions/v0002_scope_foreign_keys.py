"""Add reversible DB constraints for application-owned draft data."""
from __future__ import annotations

from db import get_app_conn

VERSION = "0002_scope_foreign_keys"
DESCRIPTION = "Enforce that application-owned drafts/channels belong to the same tenant"
REVERSIBLE = True

_CHILDREN = (
    ("app_launch_drafts", "fk_launch_draft_application_scope"),
    ("app_distribution_channels", "fk_distribution_channel_application_scope"),
    ("app_distribution_drafts", "fk_distribution_draft_application_scope"),
)


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        for table, _ in _CHILDREN:
            cur.execute(
                f"""SELECT COUNT(*) AS count FROM {table} child
                    LEFT JOIN app_applications app
                      ON app.id=child.application_id AND app.tenant_id=child.tenant_id
                    WHERE app.id IS NULL"""
            )
            if int(cur.fetchone()["count"]):
                raise RuntimeError(f"{table} 存在孤立或跨租户应用记录，拒绝添加约束")
        cur.execute(
            "ALTER TABLE app_applications "
            "ADD UNIQUE KEY uk_application_id_tenant (id, tenant_id)"
        )
        for table, constraint in _CHILDREN:
            cur.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                "FOREIGN KEY (application_id, tenant_id) "
                "REFERENCES app_applications (id, tenant_id) "
                "ON UPDATE RESTRICT ON DELETE RESTRICT"
            )
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        for table, constraint in reversed(_CHILDREN):
            cur.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {constraint}")
        cur.execute(
            "ALTER TABLE app_applications DROP INDEX uk_application_id_tenant"
        )
        conn.commit()
