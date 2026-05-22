"""阶段 7 #3 邮箱验证数据访问层。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from db import get_app_conn
from loguru import logger

_DEFAULT_TTL_HOURS = 48


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def create(*, user_id: int, email: str,
           purpose: str = "register",
           ttl_hours: int = _DEFAULT_TTL_HOURS) -> dict:
    """生成一条验证记录；并 invalidate 该 user 同 purpose 的旧记录。"""
    token = generate_token()
    expires_at = datetime.now() + timedelta(hours=ttl_hours)
    with get_app_conn() as conn:
        cur = conn.cursor()
        # 旧的 pending verification 直接置 expired（把 expires_at 设为过去）
        cur.execute(
            """UPDATE app_email_verifications
               SET expires_at = NOW() - INTERVAL 1 SECOND
               WHERE user_id = %s AND purpose = %s
                 AND verified_at IS NULL AND expires_at > NOW()""",
            (user_id, purpose),
        )
        cur.execute(
            """INSERT INTO app_email_verifications
               (user_id, email, token, purpose, expires_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, email, token, purpose, expires_at),
        )
        record_id = cur.lastrowid
        conn.commit()
    logger.info(f"为 user_id={user_id}({email}) 生成邮箱验证 token (id={record_id})")
    return get_by_id(record_id)  # type: ignore[return-value]


def get_by_id(rid: int) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM app_email_verifications WHERE id = %s", (rid,))
        return cur.fetchone()


def get_by_token(token: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM app_email_verifications WHERE token = %s", (token,))
        return cur.fetchone()


def get_active_by_user(user_id: int, purpose: str = "register") -> Optional[dict]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM app_email_verifications
               WHERE user_id = %s AND purpose = %s
                 AND verified_at IS NULL AND expires_at > NOW()
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, purpose),
        )
        return cur.fetchone()


def mark_verified(rid: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE app_email_verifications
               SET verified_at = NOW()
               WHERE id = %s AND verified_at IS NULL AND expires_at > NOW()""",
            (rid,),
        )
        conn.commit()
        return cur.rowcount > 0
