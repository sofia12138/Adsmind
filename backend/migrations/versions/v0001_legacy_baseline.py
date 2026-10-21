"""Move the legacy startup bootstrap behind an explicit operator command."""
from __future__ import annotations

VERSION = "0001_legacy_baseline"
DESCRIPTION = "Create/upgrade the existing APP and BIZ schema and seed required metadata"
REVERSIBLE = False


def upgrade() -> None:
    from config import get_settings
    from db import (
        get_app_conn,
        get_biz_conn,
        init_app_tables,
        init_biz_tables,
        migrate_json_data,
    )
    from services.distribution_service import init_tables as init_distribution_tables
    from services.launch_draft_service import init_table as init_launch_draft_table
    from services.tenant_migration import run as migrate_tenant_ownership
    from services.user_service import ensure_default_admin
    from repositories import application_repository, tenant_member_repository
    from core.tenant import INTERNAL_TENANT_ID

    init_app_tables()
    init_launch_draft_table()
    init_distribution_tables()
    init_biz_tables()
    migrate_tenant_ownership()

    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM app_tenants WHERE status='active'")
        tenants = cur.fetchall() or []
    for tenant in tenants:
        application_repository.ensure_default_for_tenant(
            int(tenant["id"]), name=f"{tenant['name']} 默认应用"
        )

    # Rows created before the application dimension are assigned only to the
    # explicit default application of their existing tenant.  No platform id,
    # credential or content hash is used to infer ownership across tenants.
    if get_settings().biz_mysql_database:
        for tenant in tenants:
            default = application_repository.ensure_default_for_tenant(int(tenant["id"]))
            with get_biz_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """UPDATE biz_ad_accounts SET application_id=%s
                       WHERE tenant_id=%s AND application_id IS NULL""",
                    (default["id"], tenant["id"]),
                )
                conn.commit()

    migrate_json_data()
    ensure_default_admin()
    tenant_member_repository.backfill_internal_members(INTERNAL_TENANT_ID)

    # The legacy helpers historically logged some failures instead of raising.
    # A read-only guard makes the explicit command fail if the required result is
    # incomplete, so a version is never recorded after a partial bootstrap.
    from migrations.schema_guard import assert_schema_ready
    assert_schema_ready()


def downgrade() -> None:
    raise RuntimeError(
        "0001 是对既有数据库的基线接管，回滚会删除历史业务表，因此禁止自动回滚；"
        "请从执行前备份恢复。"
    )
