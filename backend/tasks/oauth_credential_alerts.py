"""OAuth 凭证过期扫描任务（阶段 7 P0）。

每天扫一次：
  - 已过期 (expires_at < now)              → status='EXPIRED' + 通知
  - 14 天内将过期 (expires_at <= now+14d) → status='EXPIRING' + 通知

通知策略（MVP）：
  - 调 email_service 发邮件给租户所有 owner / admin
  - 同一凭证 + 同一状态在 7 天内只通知一次（用 app_oauth_alerts 表幂等）

调度入口：app.py 注册 `_oauth_credential_alert_job`。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from db import get_app_conn
from repositories import oauth_credential_repository as cred_repo
from repositories import tenant_member_repository
from services import email_service


_ALERT_DEDUPE_TABLE = "app_oauth_alerts"
_DEFAULT_EXPIRING_DAYS = 14
_DEDUPE_WINDOW_DAYS = 7


def _ensure_alert_table() -> None:
    """幂等创建去重表；避免重启时丢失通知历史。"""
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {_ALERT_DEDUPE_TABLE} (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                tenant_id BIGINT NOT NULL,
                platform VARCHAR(32) NOT NULL,
                external_id VARCHAR(128) NOT NULL,
                alert_kind VARCHAR(32) NOT NULL COMMENT 'EXPIRED | EXPIRING',
                notified_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_alert (tenant_id, platform, external_id, alert_kind),
                KEY idx_notified (notified_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='OAuth 凭证过期/即将过期通知去重'
        """)
        conn.commit()


def _was_recently_alerted(tenant_id: int, platform: str, external_id: str,
                          kind: str, within_days: int) -> bool:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT notified_at FROM {_ALERT_DEDUPE_TABLE}
                WHERE tenant_id=%s AND platform=%s AND external_id=%s
                  AND alert_kind=%s""",
            (tenant_id, platform, external_id, kind),
        )
        row = cur.fetchone()
        if not row:
            return False
        notified = row.get("notified_at")
        if not isinstance(notified, datetime):
            return False
        return (datetime.now() - notified) < timedelta(days=within_days)


def _record_alert(tenant_id: int, platform: str, external_id: str, kind: str) -> None:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO {_ALERT_DEDUPE_TABLE}
                  (tenant_id, platform, external_id, alert_kind, notified_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE notified_at = NOW()""",
            (tenant_id, platform, external_id, kind),
        )
        conn.commit()


def _tenant_admin_emails(tenant_id: int) -> list[str]:
    """租户内所有 owner / admin 角色的邮箱（=username）。"""
    members = tenant_member_repository.list_by_tenant(tenant_id)
    return [
        (m.get("username") or "").strip()
        for m in members
        if (m.get("tenant_role") or m.get("role") or "").lower() in ("owner", "admin")
        and m.get("username") and "@" in (m.get("username") or "")
    ]


def _tenant_name(tenant_id: int) -> str:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM app_tenants WHERE id=%s", (tenant_id,))
        row = cur.fetchone()
        return (row.get("name") if row else None) or f"Tenant#{tenant_id}"


def _public_base() -> str:
    try:
        from config import get_settings
        return (getattr(get_settings(), "public_base_url", "") or "").rstrip("/")
    except Exception:
        return ""


def _notify(*, tenant_id: int, platform: str, external_id: str,
            expires_at: Optional[datetime], kind: str) -> bool:
    emails = _tenant_admin_emails(tenant_id)
    if not emails:
        return False
    tenant_name = _tenant_name(tenant_id)
    exp_str = expires_at.strftime("%Y-%m-%d %H:%M") if isinstance(expires_at, datetime) else "未知"
    base = _public_base()
    cta = f"{base}/settings/integrations" if base else "/settings/integrations"

    if kind == "EXPIRED":
        subject = f"[AdsMind] {platform.upper()} 授权已过期：{tenant_name}"
        intro = (
            f"<b>{platform.upper()}</b> 广告账号「{external_id}」的授权已于 "
            f"<b>{exp_str}</b> 过期，相关数据同步将失败。<br/>"
            f"请打开集成中心重新授权。"
        )
    else:
        subject = f"[AdsMind] {platform.upper()} 授权即将过期：{tenant_name}"
        intro = (
            f"<b>{platform.upper()}</b> 广告账号「{external_id}」的授权将于 "
            f"<b>{exp_str}</b> 过期。<br/>请提前重新授权，避免数据同步中断。"
        )

    text = (
        f"{platform.upper()} 账号 {external_id} 的授权"
        f"{'已过期' if kind == 'EXPIRED' else '即将过期'}（{exp_str}）。\n"
        f"重新授权：{cta}\n"
    )
    html = email_service._common_html_shell(
        title=("授权已过期" if kind == "EXPIRED" else "授权即将过期"),
        intro_html=intro,
        cta_label="去重新授权",
        cta_url=cta,
        footer_note="本邮件由 AdsMind 自动发送。如果您已重新授权，可忽略本邮件。",
    )

    any_ok = False
    for to in emails:
        ok = email_service.send_email(to=to, subject=subject, text=text, html=html)
        any_ok = any_ok or ok
    return any_ok


def run(expiring_days: int = _DEFAULT_EXPIRING_DAYS) -> dict:
    """执行一次扫描；返回统计。"""
    _ensure_alert_table()
    now = datetime.now()
    soon_limit = now + timedelta(days=expiring_days)

    # list_expiring 返回的是「now+within_seconds 之前到期」的所有（含已过期）
    candidates = cred_repo.list_expiring(within_seconds=expiring_days * 86400)
    expired_count = 0
    expiring_count = 0
    notified_count = 0
    skipped_dedupe = 0

    for c in candidates:
        exp = c.get("expires_at")
        if not isinstance(exp, datetime):
            continue
        if exp < now:
            kind = "EXPIRED"
            expired_count += 1
        elif exp <= soon_limit:
            kind = "EXPIRING"
            expiring_count += 1
        else:
            continue

        tenant_id = int(c["tenant_id"])
        platform = str(c["platform"])
        external_id = str(c["external_id"])

        if _was_recently_alerted(tenant_id, platform, external_id,
                                 kind, _DEDUPE_WINDOW_DAYS):
            skipped_dedupe += 1
            continue
        ok = _notify(tenant_id=tenant_id, platform=platform,
                     external_id=external_id, expires_at=exp, kind=kind)
        if ok:
            _record_alert(tenant_id, platform, external_id, kind)
            notified_count += 1

    result = {
        "expired": expired_count,
        "expiring": expiring_count,
        "notified": notified_count,
        "skipped_dedupe": skipped_dedupe,
    }
    logger.info(f"[oauth-alerts] 扫描完成: {result}")
    return result
