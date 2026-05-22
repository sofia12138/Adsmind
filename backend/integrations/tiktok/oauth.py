"""TikTok Marketing API OAuth 2.0 授权码流程（阶段 2）。

文档：https://business-api.tiktok.com/portal/docs?id=1738373164380162

要点：
  - 授权码换 token 使用 `app_id` + `secret` + `auth_code`（TikTok 自家字段名）。
  - access_token 长期有效（一年），不返回 refresh_token；
    续期通过用户重新授权完成，因此本实现的 `refresh()` 抛 OAuthError。
  - 返回数据包含可管理的 `advertiser_ids`，调用 `/oauth2/advertiser/get/`
    可拿到 advertiser 详情；这里默认拉一次回灌到 `TokenBundle.accounts`。
"""
from __future__ import annotations

import httpx
from loguru import logger

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
            except httpx.HTTPError as e:
                raise OAuthError(f"TikTok 网络错误：{e}") from e
        data = resp.json() if resp.content else {}
        if data.get("code") != 0:
            raise OAuthError(f"TikTok 授权失败：{data.get('message') or 'unknown'}")
        d = data.get("data", {}) or {}
        access_token = d.get("access_token") or ""
        if not access_token:
            raise OAuthError("TikTok 响应缺少 access_token")
        # TikTok 文档：access_token 默认 1 年；接口若返回 access_token_expire_in 则用之
        expires_at = expires_at_from_seconds(d.get("access_token_expire_in") or 86400 * 365)
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
        """调用 `/oauth2/advertiser/get/` 拉广告主详情。失败返回退化结构。"""
        if not advertiser_ids:
            return []
        url = f"{self.api_base_url}/oauth2/advertiser/get/"
        headers = {"Access-Token": access_token, "Content-Type": "application/json"}
        params = {"app_id": self.app_id, "secret": self.app_secret}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers, params=params)
            data = resp.json()
        except Exception as e:
            logger.warning(f"TikTok 拉取 advertiser 详情失败：{e}")
            return [{"account_id": str(aid), "account_name": ""} for aid in advertiser_ids]
        if data.get("code") != 0:
            logger.warning(f"TikTok advertiser/get 非 0 响应：{data}")
            return [{"account_id": str(aid), "account_name": ""} for aid in advertiser_ids]
        out: list[dict] = []
        for a in (data.get("data", {}) or {}).get("list", []):
            out.append({
                "account_id": str(a.get("advertiser_id", "")),
                "account_name": a.get("advertiser_name", "") or "",
                "currency": a.get("currency", "USD"),
                "timezone": a.get("timezone", ""),
                "status": a.get("status", ""),
            })
        return out
