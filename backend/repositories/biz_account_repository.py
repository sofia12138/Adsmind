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
        # The platform/account key is globally unique in the legacy schema.  A
        # read-only ownership check must happen before the upsert because the
        # connection uses autocommit and ON DUPLICATE KEY could otherwise mutate
        # a same-tenant account owned by another application.
        check = conn.cursor()
        check.execute(
            'SELECT tenant_id, application_id FROM biz_ad_accounts '
            'WHERE platform=%s AND account_id=%s',
            (platform, account_id),
        )
        owner = check.fetchone()
        if owner and (
            int(owner['tenant_id']) != current_tenant_id()
            or int(owner['application_id'] or 0) != current_application_id()
        ):
            raise HTTPException(409, '此广告账户已接入其他应用，不能覆盖其凭证')
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            """INSERT INTO biz_ad_accounts
               (platform, account_id, account_name, currency, timezone, status,
                access_token, app_id, app_secret, is_default, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 account_name = IF(tenant_id = VALUES(tenant_id), VALUES(account_name), account_name),
                 currency     = VALUES(currency),
                 timezone     = VALUES(timezone),
                 status       = VALUES(status),
                 access_token = IF(tenant_id = VALUES(tenant_id), VALUES(access_token), access_token),
                 app_id       = VALUES(app_id),
                 app_secret   = VALUES(app_secret),
                 is_default   = VALUES(is_default),
                 raw_json     = VALUES(raw_json)""",
            (platform, account_id, account_name, currency, timezone, status,
             access_token, app_id, app_secret, is_default,
             json.dumps(raw_json, ensure_ascii=False) if raw_json else None),
        )
        conn.commit()
        return cur.lastrowid


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
    if tenant_id != current_tenant_id():
        raise HTTPException(403, '租户不匹配')
    return list_all()


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


def bind_to_application(account_row_id: int, application_id: Optional[int]) -> int:
    """Keep an account in the verified application; cross-app moves fail closed."""
    if application_id is None or int(application_id) != current_application_id():
        return 0
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_ad_accounts')
        cur.execute(
            "UPDATE biz_ad_accounts SET application_id = %s WHERE id = %s",
            (application_id, account_row_id),
        )
        conn.commit()
        return cur.rowcount
