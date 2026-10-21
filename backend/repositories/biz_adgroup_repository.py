"""Adgroup/Adset 列表数据访问层 -- biz_adgroups (adpilot_biz)"""
from __future__ import annotations

import json
from core.isolation import require_owned_accounts, tenant_cursor
from db import get_biz_conn


def upsert_batch(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_biz_conn() as conn:
        require_owned_accounts(conn, rows)
        cur = tenant_cursor(conn, 'biz_adgroups')
        sql = """INSERT INTO biz_adgroups
                 (platform, account_id, campaign_id, adgroup_id, adgroup_name,
                  status, is_active, raw_json)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE
                   account_id   = VALUES(account_id),
                   campaign_id  = VALUES(campaign_id),
                   adgroup_name = VALUES(adgroup_name),
                   status       = VALUES(status),
                   is_active    = VALUES(is_active),
                   raw_json     = VALUES(raw_json)"""
        params = [
            (r["platform"], r["account_id"], r.get("campaign_id", ""),
             r["adgroup_id"], r.get("adgroup_name", ""),
             r.get("status", ""), int(r.get("is_active", True)),
             json.dumps(r["raw_json"], ensure_ascii=False) if r.get("raw_json") else None)
            for r in rows
        ]
        cur.executemany(sql, params)
        conn.commit()
        return cur.rowcount


def update_status(platform: str, adgroup_id: str, status: str) -> int:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_adgroups')
        cur.execute(
            "UPDATE biz_adgroups SET status = %s, is_active = %s WHERE platform = %s AND adgroup_id = %s",
            (status, int(status in ('ACTIVE', 'ENABLE', 'ENABLED')), platform, adgroup_id),
        )
        conn.commit()
        return cur.rowcount


def list_by_platform(platform: str) -> list[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_adgroups')
        cur.execute("SELECT * FROM biz_adgroups WHERE platform = %s ORDER BY id", (platform,))
        return cur.fetchall()


def list_all() -> list[dict]:
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'biz_adgroups')
        cur.execute("SELECT * FROM biz_adgroups ORDER BY id")
        return cur.fetchall()
