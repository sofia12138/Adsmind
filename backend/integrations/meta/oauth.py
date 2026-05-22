"""Meta (Facebook) Graph API OAuth 2.0 授权码流程（阶段 2）。

文档：https://developers.facebook.com/docs/marketing-api/overview/authorization

要点：
  - 标准 OAuth2：先拿到短期 access_token，再换长期 token（60 天）。
  - Meta 同样不提供 refresh_token，需要 long-lived token 到期前重新授权或用 60 天滚动续期。
  - 拉账户列表用 `/me/adaccounts?fields=account_id,name,currency,timezone_name`。
"""
from __future__ import annotations

import httpx
from loguru import logger

from config import get_settings
from integrations.oauth_base import OAuthFlow, OAuthError, TokenBundle, expires_at_from_seconds


# 用户授权入口（受 Facebook for Developers 控制台 OAuth Redirect URI 白名单约束）
_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
# 默认 scopes（最小集合，按需扩展：catalog_management、business_management 等）
_DEFAULT_SCOPES = ["ads_read", "ads_management", "read_insights"]


class MetaOAuth(OAuthFlow):
    platform = "meta"

    def __init__(self, app_id: str = "", app_secret: str = "", api_base_url: str = ""):
        settings = get_settings()
        self.app_id = app_id or settings.meta_app_id
        self.app_secret = app_secret or settings.meta_app_secret
        self.api_base_url = (api_base_url or settings.meta_api_base_url).rstrip("/")

    def _build_url(self, redirect_uri: str, state: str) -> str:
        from urllib.parse import urlencode
        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(_DEFAULT_SCOPES),
            "response_type": "code",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> TokenBundle:
        if not self.app_id or not self.app_secret:
            raise OAuthError("Meta app_id/app_secret 未配置")
        if not redirect_uri:
            from integrations.oauth_base import default_redirect_uri
            redirect_uri = default_redirect_uri(self.platform)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. code → short-lived token
            short = await self._post_token(client, params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            })
            short_token = short.get("access_token", "")
            if not short_token:
                raise OAuthError("Meta 响应缺少 access_token")

            # 2. short → long-lived（60 天）
            long_resp = await self._post_token(client, params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_token,
            })
            long_token = long_resp.get("access_token", short_token)
            expires_in = int(long_resp.get("expires_in", short.get("expires_in", 0)) or 0)

            # 3. 拉账户列表
            accounts = await self._fetch_ad_accounts(client, long_token)

        primary = accounts[0]["account_id"] if accounts else ""
        return TokenBundle(
            access_token=long_token,
            refresh_token=None,
            expires_at=expires_at_from_seconds(expires_in),
            scopes=list(_DEFAULT_SCOPES),
            accounts=accounts,
            primary_external_id=primary,
            raw={"short": short, "long": long_resp},
        )

    async def refresh(self, refresh_token: str) -> TokenBundle:
        # Meta 没有标准 refresh_token；长期 token 到期前应引导用户重新授权
        raise OAuthError("Meta 不支持 refresh_token；请引导用户重新完成 OAuth")

    # ── internal ────────────────────────────────────────────────

    async def _post_token(self, client: httpx.AsyncClient, params: dict) -> dict:
        url = f"{self.api_base_url}/oauth/access_token"
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            raise OAuthError(f"Meta 网络错误：{e}") from e
        try:
            data = resp.json()
        except Exception:
            data = {}
        if "error" in data:
            err = data["error"]
            raise OAuthError(f"Meta 授权失败：{err.get('message') or err}")
        if not data.get("access_token"):
            raise OAuthError(f"Meta 响应异常：{data}")
        return data

    async def _fetch_ad_accounts(self, client: httpx.AsyncClient, access_token: str) -> list[dict]:
        url = f"{self.api_base_url}/me/adaccounts"
        params = {
            "fields": "account_id,name,currency,timezone_name,account_status",
            "limit": 100,
            "access_token": access_token,
        }
        try:
            resp = await client.get(url, params=params)
            data = resp.json()
        except Exception as e:
            logger.warning(f"Meta 拉取 adaccounts 失败：{e}")
            return []
        if "error" in data:
            logger.warning(f"Meta adaccounts 错误：{data['error']}")
            return []
        out: list[dict] = []
        for a in data.get("data", []) or []:
            out.append({
                # Meta 返回 act_xxxx 格式 id；保留原值
                "account_id": str(a.get("account_id", a.get("id", ""))),
                "account_name": a.get("name", "") or "",
                "currency": a.get("currency", "USD"),
                "timezone": a.get("timezone_name", ""),
                "status": "ACTIVE" if a.get("account_status") == 1 else "DISABLED",
            })
        return out
