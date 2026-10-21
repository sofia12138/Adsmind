"""广告账户数据访问层 — biz_ad_accounts (adpilot_biz)"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from db import get_biz_conn
from core.isolation import (
    application_id as current_application_id,
    tenant_cursor,
    tenant_id as current_tenant_id,
)
from fastapi import HTTPException


def upsert(*, platform: str, account_id: str, account_name: str = "",
           currency: str = "USD", timezone: str = "UTC",
           status: str = "ACTIVE", access_token: str | None = None,
           app_id: str = "", app_secret: str = "",
           is_default: int = 0, raw_json: dict | None = None) -> int:
    with get_biz_conn() as conn:
        # The global platform/account key can race across requests.  Ownership
        # therefore has to be enforced inside the atomic duplicate-key write;
        # a separate SELECT-before-INSERT is only a TOCTOU check.
        owner_condition = (
            'tenant_id = VALUES(tenant_id) '
            'AND application_id = VALUES(application_id)'
        )
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            f"""INSERT INTO biz_ad_accounts
               (platform, account_id, account_name, currency, timezone, status,
                access_token, app_id, app_secret, is_default, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 account_name = IF({owner_condition}, VALUES(account_name), account_name),
                 currency     = IF({owner_condition}, VALUES(currency), currency),
                 timezone     = IF({owner_condition}, VALUES(timezone), timezone),
                 status       = IF({owner_condition}, VALUES(status), status),
                 access_token = IF({owner_condition}, VALUES(access_token), access_token),
                 app_id       = IF({owner_condition}, VALUES(app_id), app_id),
                 app_secret   = IF({owner_condition}, VALUES(app_secret), app_secret),
                 is_default   = IF({owner_condition}, VALUES(is_default), is_default),
                 raw_json     = IF({owner_condition}, VALUES(raw_json), raw_json)""",
            (platform, account_id, account_name, currency, timezone, status,
             access_token, app_id, app_secret, is_default,
             json.dumps(raw_json, ensure_ascii=False) if raw_json else None),
        )
        check = conn.cursor()
        check.execute(
            'SELECT id, tenant_id, application_id FROM biz_ad_accounts '
            'WHERE platform=%s AND account_id=%s',
            (platform, account_id),
        )
        owner = check.fetchone()
        if not owner or (
            int(owner['tenant_id']) != current_tenant_id()
            or int(owner['application_id'] or 0) != current_application_id()
        ):
            conn.rollback()
            raise HTTPException(409, '此广告账户已接入其他应用，不能覆盖其凭证')
        conn.commit()
        return int(owner['id'])


def update_by_id(row_id: int, **fields) -> int:
    if not fields:
        return 0
    allowed = {"account_name", "currency", "timezone", "status",
               "access_token", "app_id", "app_secret", "is_default"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        return 0
    vals.append(row_id)
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(f"UPDATE biz_ad_accounts SET {', '.join(sets)} WHERE id = %s", vals)
        conn.commit()
        return cur.rowcount


def delete_by_id(row_id: int) -> int:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute("DELETE FROM biz_ad_accounts WHERE id = %s", (row_id,))
        conn.commit()
        return cur.rowcount


def get_by_id(row_id: int) -> Optional[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute("SELECT * FROM biz_ad_accounts WHERE id = %s", (row_id,))
        return cur.fetchone()


def get_by_platform_account(platform: str, account_id: str) -> Optional[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            "SELECT * FROM biz_ad_accounts WHERE platform = %s AND account_id = %s",
            (platform, account_id),
        )
        return cur.fetchone()


def _reject_scope_override(application_id: int | None) -> None:
    if application_id is not None and int(application_id) != current_application_id():
        raise HTTPException(404, '广告账户不存在')


def list_by_platform(platform: str, application_id: int | None = None) -> list[dict]:
    """List accounts from the verified application only."""
    _reject_scope_override(application_id)
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            "SELECT * FROM biz_ad_accounts WHERE platform = %s "
            "ORDER BY is_default DESC, id",
            (platform,),
        )
        return cur.fetchall()


def list_all(application_id: int | None = None) -> list[dict]:
    """List accounts from the verified application only."""
    _reject_scope_override(application_id)
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            "SELECT * FROM biz_ad_accounts ORDER BY platform, is_default DESC, id"
        )
        return cur.fetchall()


def list_active(application_id: int | None = None) -> list[dict]:
    """List active accounts from the verified application only."""
    _reject_scope_override(application_id)
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            "SELECT * FROM biz_ad_accounts WHERE status = 'ACTIVE' "
            "ORDER BY platform, is_default DESC, id"
        )
        return cur.fetchall()


def set_default(platform: str, row_id: int) -> None:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute("UPDATE biz_ad_accounts SET is_default = 0 WHERE platform = %s", (platform,))
        cur.execute("UPDATE biz_ad_accounts SET is_default = 1 WHERE id = %s AND platform = %s",
                    (row_id, platform))
        conn.commit()


def update_last_synced(row_id: int) -> None:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute("UPDATE biz_ad_accounts SET last_synced_at = %s WHERE id = %s",
                    (datetime.now(), row_id))
        conn.commit()


def list_by_application(application_id: int) -> list[dict]:
    _reject_scope_override(application_id)
    return list_all()


def list_with_application_for_tenant(tenant_id: int) -> list[dict]:
    if int(tenant_id) != current_tenant_id():
        raise HTTPException(403, '租户不匹配')
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'SELECT * FROM biz_ad_accounts WHERE tenant_id=%s '
            'ORDER BY platform, application_id, is_default DESC, id',
            (tenant_id,),
        )
        return cur.fetchall() or []


def count_distinct_for_tenant(tenant_id: int) -> int:
    """Tenant-wide aggregate for quota checks; never returns account rows."""
    if int(tenant_id) != current_tenant_id():
        raise HTTPException(403, '租户不匹配')
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'SELECT COUNT(DISTINCT account_id) AS count '
            'FROM biz_ad_accounts WHERE tenant_id=%s',
            (tenant_id,),
        )
        return int(cur.fetchone()['count'])


def exists_for_tenant(tenant_id: int, account_id: str) -> bool:
    """Tenant-wide existence check used only to avoid double-counting quota."""
    if int(tenant_id) != current_tenant_id():
        raise HTTPException(403, '租户不匹配')
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'SELECT 1 FROM biz_ad_accounts WHERE tenant_id=%s AND account_id=%s LIMIT 1',
            (tenant_id, account_id),
        )
        return cur.fetchone() is not None


def transfer_to_application(account_row_id: int, application_id: int, *,
                            from_application_id: int | None = None) -> int:
    """Transfer a tenant-owned account to another verified application.

    This is a tenant-admin operation used by the application management API.
    Ordinary account CRUD remains restricted to the current application.
    """
    from repositories import application_repository
    target = application_repository.get(int(application_id))
    if not target or int(target['tenant_id']) != current_tenant_id() or target.get('status') != 'active':
        raise HTTPException(404, '应用不存在')
    where = 'id=%s AND tenant_id=%s'
    params: list[object] = [application_id, account_row_id, current_tenant_id()]
    if from_application_id is not None:
        where += ' AND application_id=%s'
        params.append(int(from_application_id))
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE biz_ad_accounts SET application_id=%s WHERE {where}",
            params,
        )
        conn.commit()
        return cur.rowcount


def bind_to_application(account_row_id: int, application_id: Optional[int]) -> int:
    """Compatibility wrapper; application-owned accounts cannot become unowned."""
    if application_id is None:
        return 0
    return transfer_to_application(account_row_id, int(application_id))
