"""TikTok Marketing API OAuth 2.0 授权码流程（阶段 2）。

文档：https://business-api.tiktok.com/portal/docs?id=1738373164380162

要点：
  - 授权码换 token 使用 `app_id` + `secret` + `auth_code`（TikTok 自家字段名）。
  - 凭证有效期采用平台响应；需要续期时引导用户重新授权。
  - 返回数据包含可管理的 `advertiser_ids`，调用 `/oauth2/advertiser/get/`
    可拿到 advertiser 详情；这里默认拉一次回灌到 `TokenBundle.accounts`。
"""
from __future__ import annotations

import httpx

from config import get_settings
from integrations.oauth_base import OAuthFlow, OAuthError, TokenBundle, expires_at_from_seconds


_AUTH_URL = "https://business-api.tiktok.com/portal/auth"


class TikTokOAuth(OAuthFlow):
    platform = "tiktok"

    def __init__(self, app_id: str = "", app_secret: str = "", api_base_url: str = ""):
        settings = get_settings()
        self.app_id = app_id or settings.tiktok_app_id
        self.app_secret = app_secret or settings.tiktok_app_secret
        self.api_base_url = (api_base_url or settings.tiktok_api_base_url).rstrip("/")

    def _build_url(self, redirect_uri: str, state: str) -> str:
        # TikTok portal/auth 的 URL 参数：app_id / redirect_uri / state
        from urllib.parse import urlencode
        params = {"app_id": self.app_id, "redirect_uri": redirect_uri, "state": state}
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> TokenBundle:
        if not self.app_id or not self.app_secret:
            raise OAuthError("TikTok app_id/app_secret 未配置")
        url = f"{self.api_base_url}/oauth2/access_token/"
        payload = {"app_id": self.app_id, "secret": self.app_secret, "auth_code": code}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise OAuthError('连接 TikTok 失败，请重新授权') from e
        data = resp.json() if resp.content else {}
        if data.get("code") != 0:
            raise OAuthError('TikTok 拒绝本次授权，请重新连接')
        d = data.get("data", {}) or {}
        access_token = d.get("access_token") or ""
        if not access_token:
            raise OAuthError("TikTok 响应缺少 access_token")
        # 不假设凭证有效期；只采用平台明确返回的期限。
        expires_at = expires_at_from_seconds(d.get("access_token_expire_in"))
        scopes = d.get("scope") or []
        if isinstance(scopes, int):
            scopes = [str(scopes)]
        accounts = await self._fetch_advertisers(access_token, d.get("advertiser_ids", []))
        primary = accounts[0]["account_id"] if accounts else (d.get("advertiser_ids") or [""])[0]
        return TokenBundle(
            access_token=access_token,
            refresh_token=None,
            expires_at=expires_at,
            scopes=[str(s) for s in scopes] if scopes else [],
            accounts=accounts,
            primary_external_id=str(primary),
            raw=d,
        )

    async def refresh(self, refresh_token: str) -> TokenBundle:
        # TikTok Marketing API 不提供 refresh_token；需要重新授权
        raise OAuthError("TikTok 不支持 refresh_token，请引导用户重新授权")

    async def _fetch_advertisers(self, access_token: str, advertiser_ids: list[str]) -> list[dict]:
        from services.account_service import _verify_tiktok
        result = await _verify_tiktok(access_token, self.app_id, self.app_secret)
        if not result['valid']:
            raise OAuthError(result['error'])
        allowed = {str(account_id) for account_id in advertiser_ids}
        if not allowed:
            raise OAuthError('TikTok 未返回本次授权的广告账号')
        return [account for account in result['accounts'] if account['account_id'] in allowed]
