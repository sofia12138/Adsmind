"""Meta (Facebook) Graph API OAuth 2.0 授权码流程（阶段 2）。

文档：https://developers.facebook.com/docs/marketing-api/overview/authorization

要点：
  - 标准 OAuth2：先拿到短期 access_token，再换长期 token，有效期以响应为准。
  - Meta 不提供标准 refresh_token，到期后需要重新授权。
  - 拉账户列表用 `/me/adaccounts?fields=account_id,name,currency,timezone_name`。
"""
from __future__ import annotations

import httpx
import hashlib
import hmac
from urllib.parse import urlparse

from config import get_settings
from integrations.oauth_base import OAuthFlow, OAuthError, TokenBundle, expires_at_from_seconds


# 用户授权入口（受 Facebook for Developers 控制台 OAuth Redirect URI 白名单约束）
# 默认 scopes（最小集合，按需扩展：catalog_management、business_management 等）
_DEFAULT_SCOPES = ["ads_read", "ads_management"]


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
        version = urlparse(self.api_base_url).path.strip('/')
        return f"https://www.facebook.com/{version}/dialog/oauth?{urlencode(params)}"

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

            # 2. short → long-lived，使用平台返回的有效期
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
            permission_data = await self._read_graph(client, 'me/permissions', long_token)
            granted = {item['permission'] for item in permission_data.get('data', []) if item.get('status') == 'granted'}
            if not set(_DEFAULT_SCOPES).issubset(granted):
                raise OAuthError('广告读取或管理权限未获授权，请重新连接并确认授权范围')

        primary = accounts[0]["account_id"] if accounts else ""
        return TokenBundle(
            access_token=long_token,
            refresh_token=None,
            expires_at=expires_at_from_seconds(expires_in),
            scopes=sorted(granted),
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
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise OAuthError('无法连接 Meta，请重新授权') from e
        if not isinstance(data, dict) or "error" in data:
            raise OAuthError('Meta 拒绝授权，请检查应用配置及授权范围')
        if not data.get("access_token"):
            raise OAuthError('Meta 未返回有效凭证，请重新授权')
        return data

    async def _read_graph(self, client, path, access_token, params=None):
        query = dict(params or {})
        query['appsecret_proof'] = hmac.new(self.app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()
        try:
            response = await client.get(f'{self.api_base_url}/{path}', params=query,
                                        headers={'Authorization': 'Bearer '+access_token})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or 'error' in payload:
                raise OAuthError('无法读取 Meta 广告账号，请检查授权权限')
            return payload
        except (httpx.HTTPError, ValueError) as e:
            raise OAuthError('无法读取 Meta 广告账号，请稍后重新连接') from e

    async def _fetch_ad_accounts(self, client: httpx.AsyncClient, access_token: str) -> list[dict]:
        params = {
            "fields": "account_id,name,currency,timezone_name,account_status",
            "limit": 100,
        }
        out: list[dict] = []
        seen_cursors = set()
        seen_accounts = set()
        for _ in range(100):
            data = await self._read_graph(client, 'me/adaccounts', access_token, params)
            for account in data.get('data', []) or []:
                account_id = str(account.get('id') or account.get('account_id') or '')
                if account_id and not account_id.startswith('act_'):
                    account_id = 'act_'+account_id
                if not account_id or not account.get('currency') or not account.get('timezone_name'):
                    raise OAuthError('Meta 未返回完整的账号币种或时区，请检查权限')
                if account_id not in seen_accounts:
                    seen_accounts.add(account_id)
                    out.append({'account_id': account_id, 'account_name': account.get('name') or account_id,
                                'currency': account['currency'], 'timezone': account['timezone_name'],
                                'status': 'ACTIVE' if account.get('account_status') == 1 else 'DISABLED'})
            paging = data.get('paging') or {}
            if not paging.get('next'):
                return out
            after = (paging.get('cursors') or {}).get('after')
            if not after or after in seen_cursors:
                raise OAuthError('Meta 账号分页信息异常，请重新连接')
            seen_cursors.add(after)
            params['after'] = after
        raise OAuthError('账号数量超过本次读取上限，请缩小授权范围')
