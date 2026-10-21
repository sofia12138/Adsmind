"""Read-only startup check for the schema expected by this release."""
from __future__ import annotations

from config import get_settings
from db import get_app_conn, get_biz_conn


APP_BASE_REQUIREMENTS = {
    "app_tenants": {"id", "status"},
    "app_tenant_members": {"tenant_id", "user_id", "role"},
    "app_applications": {"id", "tenant_id", "status", "is_default"},
    "app_users": {"id", "username", "role"},
    "app_oauth_credentials": {"tenant_id", "platform", "external_id", "access_token_enc"},
    "app_oauth_sessions": {"tenant_id", "application_id", "user_id", "platform"},
    "app_launch_drafts": {"tenant_id", "application_id", "created_by"},
    "app_distribution_channels": {"tenant_id", "application_id"},
    "app_distribution_drafts": {"tenant_id", "application_id"},
}

APP_RESOURCE_REQUIREMENTS = {
    "app_account_groups": {"tenant_id", "application_id", "account_refs"},
    "app_creative_groups": {"tenant_id", "application_id", "asset_refs"},
    "app_naming_rules": {"tenant_id", "application_id", "rule"},
    "app_execution_records": {"tenant_id", "application_id", "status"},
    "drama_masters": {
        "tenant_id", "normalized_title", "content_fingerprint", "revision",
        "chinese_title", "catalog_type", "launched_at",
    },
    "app_application_dramas": {"tenant_id", "application_id", "drama_id", "status"},
}

APP_REQUIREMENTS = APP_BASE_REQUIREMENTS | APP_RESOURCE_REQUIREMENTS

BIZ_REQUIREMENTS = {
    "biz_ad_accounts": {"tenant_id", "application_id", "platform", "account_id"},
    "tiktok_material_uploads": {"tenant_id", "advertiser_id"},
}


def _missing(conn, requirements: dict[str, set[str]]) -> list[str]:
    cur = conn.cursor()
    missing: list[str] = []
    for table, expected in requirements.items():
        cur.execute(
            """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s""",
            (table,),
        )
        actual = {row["COLUMN_NAME"] for row in (cur.fetchall() or [])}
        if not actual:
            missing.append(f"{table} (table)")
            continue
        missing.extend(f"{table}.{column}" for column in sorted(expected - actual))
    return missing


def assert_schema_ready() -> None:
    """Guard the immutable 0001 baseline without future-version requirements."""
    missing: list[str] = []
    with get_app_conn() as conn:
        missing.extend(f"APP:{item}" for item in _missing(conn, APP_BASE_REQUIREMENTS))
    if get_settings().biz_mysql_database:
        with get_biz_conn() as conn:
            missing.extend(f"BIZ:{item}" for item in _missing(conn, BIZ_REQUIREMENTS))
            if not missing:
                cur = conn.cursor()
                cur.execute(
                    """SELECT COUNT(*) AS count FROM biz_ad_accounts
                       WHERE tenant_id IS NULL OR application_id IS NULL"""
                )
                if int(cur.fetchone()["count"]):
                    missing.append("BIZ:biz_ad_accounts ownership backfill")
    if missing:
        details = ", ".join(missing)
        raise RuntimeError(
            "数据库结构未迁移，应用拒绝自动修改数据库。"
            "请先审查并显式执行 `python -m migrations.cli plan` 和 "
            f"`python -m migrations.cli upgrade`。缺失：{details}"
        )


def assert_release_schema_ready() -> None:
    """Guard every table required by the current release at application startup."""
    assert_schema_ready()
    with get_app_conn() as conn:
        missing = [f"APP:{item}" for item in _missing(conn, APP_RESOURCE_REQUIREMENTS)]
    if missing:
        details = ", ".join(missing)
        raise RuntimeError(
            "数据库结构未迁移，应用拒绝自动修改数据库。"
            "请先审查并显式执行 `python -m migrations.cli plan` 和 "
            f"`python -m migrations.cli upgrade`。缺失：{details}"
        )
