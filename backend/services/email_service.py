"""邮件发送服务（阶段 7 P0）。

设计：
  1. `EmailSender` 抽象 + 多 backend 实现，按 settings.email_backend 路由：
        - `console` (默认)：把邮件打印到日志，开发/演示环境用
        - `smtp`        ：标准 SMTP（Gmail / SES SMTP / 自建邮件服务器都可用）
        - `disabled`    ：完全静默，仅记录指标
  2. 模板：注册验证 + 团队邀请，HTML + 纯文本 fallback
  3. 健壮性：发送失败**只记录日志，不抛异常**，避免因为邮件挂掉影响主流程（注册/邀请仍成功）
  4. 配置不全时自动 fallback 到 console，不阻断启动

详见 docs/saas-transformation.md §31。
"""
from __future__ import annotations

import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from loguru import logger


# ─────────────────────────────────────────────────────────────
# 抽象层
# ─────────────────────────────────────────────────────────────

@dataclass
class EmailMessageDTO:
    to: str
    subject: str
    text: str
    html: Optional[str] = None
    from_addr: Optional[str] = None        # 缺省走 settings.email_from
    from_name: Optional[str] = None
    reply_to: Optional[str] = None


class EmailSendError(Exception):
    """邮件发送失败；上层一般 catch 后只记日志。"""


class EmailSender(ABC):
    @abstractmethod
    def send(self, msg: EmailMessageDTO) -> None: ...

    @property
    @abstractmethod
    def kind(self) -> str: ...


# ─────────────────────────────────────────────────────────────
# Console backend（开发 / 演示）
# ─────────────────────────────────────────────────────────────

class ConsoleEmailSender(EmailSender):
    @property
    def kind(self) -> str:
        return "console"

    def send(self, msg: EmailMessageDTO) -> None:
        logger.info(
            "📧 [console-email] to={to} subject={subj!r}\n"
            "---- text body ----\n{text}\n-------------------",
            to=msg.to, subj=msg.subject, text=msg.text,
        )


# ─────────────────────────────────────────────────────────────
# SMTP backend
# ─────────────────────────────────────────────────────────────

class SMTPEmailSender(EmailSender):
    def __init__(self, *, host: str, port: int, username: str, password: str,
                 use_tls: bool = True, use_ssl: bool = False,
                 default_from: str, default_from_name: str = "",
                 timeout: int = 15):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls and not use_ssl
        self.use_ssl = use_ssl
        self.default_from = default_from
        self.default_from_name = default_from_name
        self.timeout = timeout

    @property
    def kind(self) -> str:
        return "smtp"

    def send(self, msg: EmailMessageDTO) -> None:
        from_addr = msg.from_addr or self.default_from
        from_name = msg.from_name or self.default_from_name
        em = EmailMessage()
        em["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
        em["To"] = msg.to
        em["Subject"] = msg.subject
        if msg.reply_to:
            em["Reply-To"] = msg.reply_to
        em.set_content(msg.text)
        if msg.html:
            em.add_alternative(msg.html, subtype="html")

        try:
            if self.use_ssl:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port,
                                      context=ctx, timeout=self.timeout) as s:
                    if self.username:
                        s.login(self.username, self.password)
                    s.send_message(em)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                    if self.use_tls:
                        ctx = ssl.create_default_context()
                        s.starttls(context=ctx)
                    if self.username:
                        s.login(self.username, self.password)
                    s.send_message(em)
            logger.info(
                f"📧 [smtp] 已发送：to={msg.to} subject={msg.subject!r}"
            )
        except Exception as e:
            raise EmailSendError(f"SMTP 发送失败 host={self.host}:{self.port}: {e}") from e


# ─────────────────────────────────────────────────────────────
# Disabled backend（生产关闭邮件）
# ─────────────────────────────────────────────────────────────

class DisabledEmailSender(EmailSender):
    @property
    def kind(self) -> str:
        return "disabled"

    def send(self, msg: EmailMessageDTO) -> None:
        logger.debug(f"[email-disabled] skipped to={msg.to} subject={msg.subject!r}")


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────

_sender_cache: Optional[EmailSender] = None


def get_sender() -> EmailSender:
    """按 settings 决定 backend；惰性初始化 + 进程内缓存。"""
    global _sender_cache
    if _sender_cache is not None:
        return _sender_cache

    try:
        from config import get_settings
        s = get_settings()
        backend = (getattr(s, "email_backend", "") or "console").strip().lower()

        if backend == "disabled":
            _sender_cache = DisabledEmailSender()
            logger.info("[email] backend=disabled（所有邮件将被静默丢弃）")
            return _sender_cache

        if backend == "smtp":
            host = (getattr(s, "smtp_host", "") or "").strip()
            if not host:
                logger.warning("[email] backend=smtp 但未配置 smtp_host，退化为 console")
                _sender_cache = ConsoleEmailSender()
                return _sender_cache
            _sender_cache = SMTPEmailSender(
                host=host,
                port=int(getattr(s, "smtp_port", 587) or 587),
                username=getattr(s, "smtp_username", "") or "",
                password=getattr(s, "smtp_password", "") or "",
                use_tls=bool(getattr(s, "smtp_use_tls", True)),
                use_ssl=bool(getattr(s, "smtp_use_ssl", False)),
                default_from=getattr(s, "email_from", "") or "no-reply@adsmind.local",
                default_from_name=getattr(s, "email_from_name", "") or "AdsMind",
                timeout=int(getattr(s, "smtp_timeout_sec", 15) or 15),
            )
            logger.info(
                f"[email] backend=smtp host={host}:{_sender_cache.port} "
                f"tls={_sender_cache.use_tls} ssl={_sender_cache.use_ssl}"
            )
            return _sender_cache

        # 默认 console
        _sender_cache = ConsoleEmailSender()
        logger.info("[email] backend=console（开发模式：邮件打印到日志）")
        return _sender_cache
    except Exception as e:
        logger.warning(f"[email] sender 初始化失败，回落 console：{e}")
        _sender_cache = ConsoleEmailSender()
        return _sender_cache


def reset_sender_cache() -> None:
    """配置热更新 / 测试用：清掉缓存，下次重新读 settings。"""
    global _sender_cache
    _sender_cache = None


# ─────────────────────────────────────────────────────────────
# 高层封装：业务方调用入口
# ─────────────────────────────────────────────────────────────

def send_email(*, to: str, subject: str, text: str,
               html: Optional[str] = None,
               reply_to: Optional[str] = None) -> bool:
    """统一入口；返回是否发送成功。任何异常被捕获后只记日志，不抛出。"""
    if not to or "@" not in to:
        logger.warning(f"[email] 跳过：收件人非法 to={to!r}")
        return False
    sender = get_sender()
    try:
        sender.send(EmailMessageDTO(to=to, subject=subject, text=text,
                                    html=html, reply_to=reply_to))
        return True
    except Exception as e:
        logger.error(f"[email] 发送失败（已吞掉异常）to={to} subject={subject!r}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 业务模板
# ─────────────────────────────────────────────────────────────

_BRAND = "AdsMind"


def _common_html_shell(title: str, intro_html: str, cta_label: str,
                        cta_url: str, footer_note: str = "") -> str:
    """统一品牌信封；按钮 + 兜底纯链接。"""
    safe_url = (cta_url or "").replace('"', "&quot;")
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f7fb;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f6f7fb;padding:32px 0;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;
                    box-shadow:0 2px 10px rgba(0,0,0,.04);padding:32px;">
        <tr><td style="font-size:20px;font-weight:600;color:#111;padding-bottom:8px;">{_BRAND}</td></tr>
        <tr><td style="font-size:16px;font-weight:600;color:#111;padding:8px 0 16px;">{title}</td></tr>
        <tr><td style="font-size:14px;color:#444;line-height:1.7;">{intro_html}</td></tr>
        <tr><td style="padding:24px 0 8px;">
          <a href="{safe_url}"
             style="display:inline-block;padding:10px 24px;background:#2563eb;color:#fff;
                    border-radius:8px;text-decoration:none;font-size:14px;font-weight:500;">
            {cta_label}
          </a>
        </td></tr>
        <tr><td style="font-size:12px;color:#888;padding-top:12px;word-break:break-all;">
          如按钮无法点击，请复制此链接到浏览器：<br/>
          <span style="color:#2563eb;">{safe_url}</span>
        </td></tr>
        {('<tr><td style="font-size:12px;color:#999;padding-top:24px;border-top:1px solid #eee;margin-top:24px;">'
          + footer_note + '</td></tr>') if footer_note else ''}
      </table>
    </td></tr>
  </table>
</body></html>
"""


def send_verify_email(*, to: str, verify_url: str,
                      expires_in_hours: int = 48) -> bool:
    subject = f"[{_BRAND}] 请验证您的邮箱"
    text = (
        f"欢迎使用 {_BRAND}。\n\n"
        f"请在 {expires_in_hours} 小时内点击下方链接完成邮箱验证：\n"
        f"{verify_url}\n\n"
        f"如果这不是您本人的操作，请忽略本邮件。"
    )
    html = _common_html_shell(
        title="请验证您的邮箱",
        intro_html=(
            f"感谢注册 {_BRAND}。请点击下方按钮在 "
            f"<b>{expires_in_hours} 小时</b>内完成邮箱验证。"
        ),
        cta_label="立即验证邮箱",
        cta_url=verify_url,
        footer_note="如果这不是您本人的操作，请忽略此邮件。",
    )
    return send_email(to=to, subject=subject, text=text, html=html)


def send_invitation_email(*, to: str, tenant_name: str,
                          inviter_display_name: str,
                          role: str, invitation_url: str,
                          expires_in_days: int = 7) -> bool:
    role_label = {"owner": "所有者", "admin": "管理员", "member": "成员"}.get(role, role)
    subject = f"[{_BRAND}] {inviter_display_name} 邀请您加入 {tenant_name}"
    text = (
        f"{inviter_display_name} 邀请您以 {role_label} 角色加入团队"
        f"「{tenant_name}」。\n\n"
        f"请在 {expires_in_days} 天内点击下方链接接受邀请：\n"
        f"{invitation_url}\n\n"
        f"如果您不认识发件人，可以忽略此邮件。"
    )
    html = _common_html_shell(
        title=f"邀请您加入 {tenant_name}",
        intro_html=(
            f"<b>{inviter_display_name}</b> 邀请您以 <b>{role_label}</b> "
            f"角色加入团队「<b>{tenant_name}</b>」。"
            f"<br/>邀请将在 <b>{expires_in_days} 天</b>后过期。"
        ),
        cta_label="接受邀请",
        cta_url=invitation_url,
        footer_note="如果您不认识发件人或不希望加入该团队，可以忽略此邮件。",
    )
    return send_email(to=to, subject=subject, text=text, html=html)
