"""广告账户数据访问层 — biz_ad_accounts (adpilot_biz)"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from db import get_biz_conn


def upsert(*, platform: str, account_id: str, account_name: str = "",
           currency: str = "USD", timezone: str = "UTC",
           status: str = "ACTIVE", access_token: str | None = None,
           app_id: str = "", app_secret: str = "",
           is_default: int = 0, raw_json: dict | None = None) -> int:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO biz_ad_accounts
               (platform, account_id, account_name, currency, timezone, status,
                access_token, app_id, app_secret, is_default, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 account_name = VALUES(account_name),
                 currency     = VALUES(currency),
                 timezone     = VALUES(timezone),
                 status       = VALUES(status),
                 access_token = VALUES(access_token),
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
        cur = conn.cursor()
        cur.execute(f"UPDATE biz_ad_accounts SET {', '.join(sets)} WHERE id = %s", vals)
        conn.commit()
        return cur.rowcount


def delete_by_id(row_id: int) -> int:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM biz_ad_accounts WHERE id = %s", (row_id,))
        conn.commit()
        return cur.rowcount


def get_by_id(row_id: int) -> Optional[dict]:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM biz_ad_accounts WHERE id = %s", (row_id,))
        return cur.fetchone()


def get_by_platform_account(platform: str, account_id: str) -> Optional[dict]:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM biz_ad_accounts WHERE platform = %s AND account_id = %s",
            (platform, account_id),
        )
        return cur.fetchone()


def list_by_platform(platform: str, application_id: int | None = None) -> list[dict]:
    """按平台查账号。

    `application_id` 阶段 4 X3-filter：传入非 None 时严格按应用过滤；
    传 None 时返回全租户账号（向后兼容旧调用方与默认应用"全租户视角"）。
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        if application_id is not None and _application_id_column_exists():
            cur.execute(
                "SELECT * FROM biz_ad_accounts "
                "WHERE platform = %s AND application_id = %s "
                "ORDER BY is_default DESC, id",
                (platform, application_id),
            )
        else:
            cur.execute(
                "SELECT * FROM biz_ad_accounts WHERE platform = %s "
                "ORDER BY is_default DESC, id",
                (platform,),
            )
        return cur.fetchall()


def list_all(application_id: int | None = None) -> list[dict]:
    """列出全部账号。

    `application_id`：传入非 None 时严格按应用过滤；传 None 表示全租户视角。
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        if application_id is not None and _application_id_column_exists():
            cur.execute(
                "SELECT * FROM biz_ad_accounts WHERE application_id = %s "
                "ORDER BY platform, is_default DESC, id",
                (application_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM biz_ad_accounts ORDER BY platform, is_default DESC, id"
            )
        return cur.fetchall()


def list_active(application_id: int | None = None) -> list[dict]:
    """列出 ACTIVE 状态账号，可选按应用过滤。"""
    with get_biz_conn() as conn:
        cur = conn.cursor()
        if application_id is not None and _application_id_column_exists():
            cur.execute(
                "SELECT * FROM biz_ad_accounts "
                "WHERE status = 'ACTIVE' AND application_id = %s "
                "ORDER BY platform, is_default DESC, id",
                (application_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM biz_ad_accounts WHERE status = 'ACTIVE' "
                "ORDER BY platform, is_default DESC, id"
            )
        return cur.fetchall()


def set_default(platform: str, row_id: int) -> None:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE biz_ad_accounts SET is_default = 0 WHERE platform = %s", (platform,))
        cur.execute("UPDATE biz_ad_accounts SET is_default = 1 WHERE id = %s AND platform = %s",
                    (row_id, platform))
        conn.commit()


def update_last_synced(row_id: int) -> None:
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE biz_ad_accounts SET last_synced_at = %s WHERE id = %s",
                    (datetime.now(), row_id))
        conn.commit()


# ── 阶段 4 X3：应用归属 ────────────────────────────────────────────

def _application_id_column_exists() -> bool:
    """运行时检测 biz_ad_accounts 是否已加 application_id 列。

    迁移 003 未跑前，相关接口安全降级为空列表，不会 500。
    """
    try:
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'biz_ad_accounts'
                     AND COLUMN_NAME = 'application_id' LIMIT 1"""
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def list_by_application(application_id: int) -> list[dict]:
    """列出绑定到指定应用的全部账号。列未就绪时返回 []。"""
    if not _application_id_column_exists():
        return []
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM biz_ad_accounts WHERE application_id = %s "
            "ORDER BY platform, is_default DESC, id",
            (application_id,),
        )
        return cur.fetchall() or []


def list_with_application_for_tenant(tenant_id: int) -> list[dict]:
    """列出该 tenant 下所有账号（已绑定 + 未绑定）。

    阶段 4 X3 临时实现：当前 biz_ad_accounts 仍可能没有 tenant_id（早于 001 加列），
    所以这里按 internal tenant 视角返回全部账号，前端区分 application_id 字段
    自行渲染"已绑定 / 未绑定"。
    """
    if not _application_id_column_exists():
        rows = list_all()
        for r in rows:
            r["application_id"] = None
        return rows
    with get_biz_conn() as conn:
        cur = conn.cursor()
        # 兼容是否含 tenant_id 列
        cur.execute(
            """SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE()
                 AND TABLE_NAME = 'biz_ad_accounts'
                 AND COLUMN_NAME = 'tenant_id' LIMIT 1"""
        )
        has_tenant = cur.fetchone() is not None
        if has_tenant:
            cur.execute(
                "SELECT * FROM biz_ad_accounts WHERE tenant_id = %s OR tenant_id IS NULL "
                "ORDER BY platform, application_id IS NULL, is_default DESC, id",
                (tenant_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM biz_ad_accounts "
                "ORDER BY platform, application_id IS NULL, is_default DESC, id"
            )
        return cur.fetchall() or []


def bind_to_application(account_row_id: int, application_id: Optional[int]) -> int:
    """绑定（或传 None 解绑）账号到应用。列未就绪时静默返回 0。"""
    if not _application_id_column_exists():
        return 0
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE biz_ad_accounts SET application_id = %s WHERE id = %s",
            (application_id, account_row_id),
        )
        conn.commit()
        return cur.rowcount
