"""Campaign 数据访问层 — biz_campaigns (adpilot_biz)"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import require_owned_accounts, tenant_cursor
from db import get_biz_conn


def upsert(*, platform: str, account_id: str, campaign_id: str,
           campaign_name: str = "", objective: str = "",
           buying_type: str = "", status: str = "",
           is_active: bool = True, raw_json: dict | None = None) -> int:
    with get_biz_conn() as conn:
        require_owned_accounts(conn, ({'platform': platform, 'account_id': account_id},))
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute(
            """INSERT INTO biz_campaigns
               (platform, account_id, campaign_id, campaign_name,
                objective, buying_type, status, is_active, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 account_id    = VALUES(account_id),
                 campaign_name = VALUES(campaign_name),
                 objective     = VALUES(objective),
                 buying_type   = VALUES(buying_type),
                 status        = VALUES(status),
                 is_active     = VALUES(is_active),
                 raw_json      = VALUES(raw_json)""",
            (platform, account_id, campaign_id, campaign_name,
             objective, buying_type, status, int(is_active),
             json.dumps(raw_json, ensure_ascii=False) if raw_json else None),
        )
        conn.commit()
        return cur.lastrowid


def upsert_batch(rows: list[dict]) -> int:
    """批量 upsert，rows 中每个 dict 需含 upsert() 所需字段。返回影响行数。"""
    if not rows:
        return 0
    with get_biz_conn() as conn:
        require_owned_accounts(conn, rows)
        cur = tenant_cursor(conn, 'biz_campaigns')
        sql = """INSERT INTO biz_campaigns
                 (platform, account_id, campaign_id, campaign_name,
                  objective, buying_type, status, is_active, raw_json)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE
                   account_id    = VALUES(account_id),
                   campaign_name = VALUES(campaign_name),
                   objective     = VALUES(objective),
                   buying_type   = VALUES(buying_type),
                   status        = VALUES(status),
                   is_active     = VALUES(is_active),
                   raw_json      = VALUES(raw_json)"""
        params = [
            (r["platform"], r["account_id"], r["campaign_id"],
             r.get("campaign_name", ""), r.get("objective", ""),
             r.get("buying_type", ""), r.get("status", ""),
             int(r.get("is_active", True)),
             json.dumps(r["raw_json"], ensure_ascii=False) if r.get("raw_json") else None)
            for r in rows
        ]
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


def get_by_platform_campaign(platform: str, campaign_id: str) -> Optional[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute(
            "SELECT * FROM biz_campaigns WHERE platform = %s AND campaign_id = %s",
            (platform, campaign_id),
        )
        return cur.fetchone()


def list_by_account(platform: str, account_id: str) -> list[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute(
            "SELECT * FROM biz_campaigns WHERE platform = %s AND account_id = %s ORDER BY id",
            (platform, account_id),
        )
        return cur.fetchall()


def list_by_platform(platform: str) -> list[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute(
            "SELECT * FROM biz_campaigns WHERE platform = %s ORDER BY id",
            (platform,),
        )
        return cur.fetchall()


def update_status(platform: str, campaign_id: str, status: str) -> int:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute(
            "UPDATE biz_campaigns SET status = %s, is_active = %s WHERE platform = %s AND campaign_id = %s",
            (status, int(status in ('ACTIVE', 'ENABLE', 'ENABLED')), platform, campaign_id),
        )
        conn.commit()
        return cur.rowcount


def list_all() -> list[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_campaigns')
        cur.execute("SELECT * FROM biz_campaigns ORDER BY id")
        return cur.fetchall()
