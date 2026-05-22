"""统一的 OAuth 授权码流程抽象（阶段 2）。

设计：
  - `OAuthFlow` 抽象基类：每个平台实现 `build_authorize_url` + `exchange_code` + `refresh`。
  - `TokenBundle` DTO：包含 access_token、可选 refresh_token、过期时间、scopes、
    以及该平台返回的"账户列表"（用于落地到 `biz_ad_accounts`）。
  - `state` 自包含 HMAC：`base64(tenant_id|platform|nonce|ts|hmac)`，
    服务端无需存储任何中间状态；回调时校验签名 + TTL。

详见 docs/saas-transformation.md §7.6、§9.1。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_settings


# ── DTO ───────────────────────────────────────────────────────────

@dataclass
class TokenBundle:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = field(default_factory=list)
    # 平台返回的可管理账户列表，元素形如：
    #   {"account_id": "xxx", "account_name": "...", "currency": "USD", "timezone": "..."}
    accounts: list[dict] = field(default_factory=list)
    # 该 access_token 在平台侧的归属标识（advertiser_id / business_id / customer_id）
    primary_external_id: str = ""
    # 平台原始 JSON（供审计 / 调试）
    raw: dict = field(default_factory=dict)


class OAuthError(Exception):
    """OAuth 流程异常，message 会回显给前端，不要包含敏感数据。"""


# ── State 自包含签名 ─────────────────────────────────────────────

def _state_secret() -> bytes:
    settings = get_settings()
    secret = (settings.oauth_state_secret or settings.jwt_secret_key or "change-me").encode("utf-8")
    return secret


def build_state(tenant_id: int, platform: str, extra: Optional[dict] = None) -> str:
    """构造 self-contained state：包含 tenant_id / platform / nonce / ts + HMAC 签名。"""
    payload = {
        "t": int(tenant_id),
        "p": platform,
        "n": secrets.token_urlsafe(16),
        "ts": int(time.time()),
    }
    if extra:
        payload["x"] = extra
    body_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(_state_secret(), body_b64.encode(), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return f"{body_b64}.{sig}"


def verify_state(state: str) -> dict:
    """校验签名 + TTL；成功返回 payload，失败抛 OAuthError。"""
    settings = get_settings()
    if not state or "." not in state:
        raise OAuthError("state 缺失或格式错误")
    body_b64, sig_b64 = state.split(".", 1)
    expected = hmac.new(_state_secret(), body_b64.encode(), hashlib.sha256).digest()
    expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(sig_b64, expected_b64):
        raise OAuthError("state 签名校验失败")
    try:
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception as e:
        raise OAuthError("state 解码失败") from e

    ts = int(payload.get("ts", 0))
    if not ts or time.time() - ts > settings.oauth_state_ttl_sec:
        raise OAuthError("state 已过期")
    return payload


# ── 工具 ──────────────────────────────────────────────────────────

def expires_at_from_seconds(seconds: Optional[int]) -> Optional[datetime]:
    if not seconds or seconds <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds))


def default_redirect_uri(platform: str) -> str:
    settings = get_settings()
    base = (settings.oauth_redirect_base_url or "").rstrip("/")
    return f"{base}/api/integrations/{platform}/oauth/callback"


# ── 抽象基类 ──────────────────────────────────────────────────────

class OAuthFlow(ABC):
    """所有平台 OAuth 流程的统一接口。"""

    platform: str = ""

    def build_authorize_url(self, tenant_id: int, redirect_uri: Optional[str] = None,
                            extra: Optional[dict] = None) -> dict:
        """生成跳转 URL；返回 `{authorize_url, state}` 供前端使用。"""
        state = build_state(tenant_id, self.platform, extra=extra)
        url = self._build_url(redirect_uri or default_redirect_uri(self.platform), state)
        return {"authorize_url": url, "state": state, "platform": self.platform}

    @abstractmethod
    def _build_url(self, redirect_uri: str, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> TokenBundle:
        """授权码 → 完整 TokenBundle。"""

    @abstractmethod
    async def refresh(self, refresh_token: str) -> TokenBundle:
        """refresh_token → 新 TokenBundle；不支持时抛 OAuthError。"""
