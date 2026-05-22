"""OAuth 凭证数据访问层 —— 封装 `app_oauth_credentials` 表，所有读写自动加解密。

阶段 2 用途：
  - 替换 `biz_ad_accounts.access_token` 明文存储；
  - 支持 refresh_token + 过期时间，后台 job 续期；
  - AAD 绑定 `f"tenant:{tenant_id}|platform:{platform}|ext:{external_id}"`，
    防止跨租户/跨平台密文重放。

详见 docs/saas-transformation.md §7.5、§7.6。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from db import get_app_conn
from core import crypto


# ── AAD 工具 ──────────────────────────────────────────────────────

def _aad(tenant_id: int, platform: str, external_id: str) -> bytes:
    return f"tenant:{tenant_id}|platform:{platform}|ext:{external_id}".encode("utf-8")


# ── 写入 ──────────────────────────────────────────────────────────

def upsert(*, tenant_id: int, platform: str, external_id: str,
           access_token: str, refresh_token: Optional[str] = None,
           expires_at: Optional[datetime] = None,
           scopes: Optional[list[str]] = None) -> int:
    """加密后写入凭证；存在则覆盖。返回受影响行 id。"""
    if not (tenant_id and platform and external_id and access_token):
        raise ValueError("tenant_id/platform/external_id/access_token 不能为空")

    aad = _aad(tenant_id, platform, external_id)
    access_blob = crypto.encrypt(access_token, aad=aad)
    refresh_blob = crypto.encrypt(refresh_token, aad=aad) if refresh_token else None
    scopes_json = json.dumps(scopes, ensure_ascii=False) if scopes else None

    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO app_oauth_credentials
                 (tenant_id, platform, external_id, access_token_enc, refresh_token_enc,
                  expires_at, scopes)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 access_token_enc  = VALUES(access_token_enc),
                 refresh_token_enc = VALUES(refresh_token_enc),
                 expires_at        = VALUES(expires_at),
                 scopes            = VALUES(scopes)""",
            (tenant_id, platform, external_id, access_blob, refresh_blob,
             expires_at, scopes_json),
        )
        conn.commit()
        # 取最终行 id（lastrowid 在 ON DUPLICATE KEY UPDATE 下可能为 0）
        cur.execute(
            "SELECT id FROM app_oauth_credentials WHERE tenant_id=%s AND platform=%s AND external_id=%s",
            (tenant_id, platform, external_id),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else 0


# ── 读取 ──────────────────────────────────────────────────────────

def get_access_token(tenant_id: int, platform: str, external_id: str) -> Optional[str]:
    """读取并解密 access_token；不存在或解密失败返回 None。"""
    row = _get_row(tenant_id, platform, external_id)
    if not row or not row.get("access_token_enc"):
        return None
    aad = _aad(tenant_id, platform, external_id)
    try:
        return crypto.decrypt(row["access_token_enc"], aad=aad)
    except crypto.CryptoError:
        return None


def get_refresh_token(tenant_id: int, platform: str, external_id: str) -> Optional[str]:
    row = _get_row(tenant_id, platform, external_id)
    if not row or not row.get("refresh_token_enc"):
        return None
    aad = _aad(tenant_id, platform, external_id)
    try:
        return crypto.decrypt(row["refresh_token_enc"], aad=aad)
    except crypto.CryptoError:
        return None


def get_meta(tenant_id: int, platform: str, external_id: str) -> Optional[dict]:
    """返回该凭证的非敏感元信息（不含密文）。"""
    row = _get_row(tenant_id, platform, external_id)
    if not row:
        return None
    scopes_raw = row.get("scopes")
    if isinstance(scopes_raw, str):
        try:
            scopes = json.loads(scopes_raw) or []
        except Exception:
            scopes = []
    elif isinstance(scopes_raw, list):
        scopes = scopes_raw
    else:
        scopes = []
    return {
        "id": int(row["id"]),
        "tenant_id": int(row["tenant_id"]),
        "platform": row["platform"],
        "external_id": row["external_id"],
        "expires_at": row.get("expires_at"),
        "scopes": scopes,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _get_row(tenant_id: int, platform: str, external_id: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM app_oauth_credentials
               WHERE tenant_id=%s AND platform=%s AND external_id=%s""",
            (tenant_id, platform, external_id),
        )
        return cur.fetchone()


# ── 列表 / 查询 ─────────────────────────────────────────────────

def list_by_tenant(tenant_id: int, platform: Optional[str] = None) -> list[dict]:
    sql = (
        "SELECT id, tenant_id, platform, external_id, expires_at, scopes, "
        "created_at, updated_at FROM app_oauth_credentials WHERE tenant_id=%s"
    )
    params: list = [tenant_id]
    if platform:
        sql += " AND platform=%s"
        params.append(platform)
    sql += " ORDER BY platform, external_id"
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() or []


def list_expiring(within_seconds: int) -> list[dict]:
    """返回 N 秒内即将过期的凭证元信息（不含密文），供 refresh job 使用。"""
    sql = (
        "SELECT id, tenant_id, platform, external_id, expires_at "
        "FROM app_oauth_credentials "
        "WHERE expires_at IS NOT NULL "
        "  AND expires_at <= DATE_ADD(NOW(), INTERVAL %s SECOND)"
    )
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (within_seconds,))
        return cur.fetchall() or []


# ── 删除 ──────────────────────────────────────────────────────────

def delete(tenant_id: int, platform: str, external_id: str) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM app_oauth_credentials "
            "WHERE tenant_id=%s AND platform=%s AND external_id=%s",
            (tenant_id, platform, external_id),
        )
        conn.commit()
        return cur.rowcount > 0
