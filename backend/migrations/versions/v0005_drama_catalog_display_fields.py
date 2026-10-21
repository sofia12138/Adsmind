"""Add the lightweight fields used by the self-operated/distribution lists."""
from __future__ import annotations

from db import get_app_conn


VERSION = "0005_drama_catalog_display_fields"
DESCRIPTION = "Add Chinese title, catalog type and launch date to drama masters"
REVERSIBLE = True


def upgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """ALTER TABLE drama_masters
               ADD COLUMN chinese_title VARCHAR(255) NOT NULL DEFAULT '' AFTER title,
               ADD COLUMN catalog_type VARCHAR(24) NOT NULL DEFAULT 'self_operated' AFTER tenant_id,
               ADD COLUMN launched_at DATE DEFAULT NULL AFTER original_language,
               ADD KEY idx_drama_catalog_list (tenant_id, catalog_type, launched_at, id)"""
        )
        conn.commit()


def downgrade() -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("ALTER TABLE drama_masters DROP INDEX idx_drama_catalog_list")
        cur.execute(
            """ALTER TABLE drama_masters
               DROP COLUMN launched_at,
               DROP COLUMN catalog_type,
               DROP COLUMN chinese_title"""
        )
        conn.commit()
