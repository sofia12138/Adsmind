"""Meta (Facebook) Marketing API HTTP 客户端 — 全局连接池复用"""

from __future__ import annotations
import httpx
from loguru import logger
from config import get_settings

_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _shared_client


class MetaApiError(Exception):
    def __init__(self, code: int, message: str, fbtrace_id: str = "",
                 error_subcode: int = 0, error_user_msg: str = ""):
        self.code = code
        self.message = message
        self.fbtrace_id = fbtrace_id
        self.error_subcode = error_subcode
        self.error_user_msg = error_user_msg
        parts = [f"[{code}] {message}"]
        if error_subcode:
            parts.append(f"subcode={error_subcode}")
        if error_user_msg:
            parts.append(error_user_msg)
        if fbtrace_id:
            parts.append(f"fbtrace={fbtrace_id}")
        super().__init__(" | ".join(parts))


class MetaClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        account_id: str | None = None,
        tenant_id: int | None = None,
    ):
        """构造 Meta Graph API 客户端。

        access_token 解析顺序（向后兼容）：
          1. 调用方显式传入的 `access_token`
          2. `services.credential_service.resolve_access_token()`：
             - 加密表 `app_oauth_credentials`
             - 旧明文 `biz_ad_accounts.access_token`
             - `.env` 默认 `META_ACCESS_TOKEN`

        阶段 2 起推荐传 `account_id`（+ 可选 `tenant_id`）。
        """
        settings = get_settings()
        self.base_url = settings.meta_api_base_url
        if account_id:
            from services.credential_service import _check_account_scope
            from core.isolation import tenant_id as current_tenant_id
            _check_account_scope(tenant_id if tenant_id is not None else current_tenant_id(), 'meta', account_id)

        token = access_token
        token_source = "explicit" if token else "none"
        if not token:
            from services.credential_service import resolve_token_source
            token, token_source = resolve_token_source(
                "meta", account_id=account_id, tenant_id=tenant_id,
            )
        self.access_token = token or ""
        if not access_token:
            # 仅在没显式传 token 时打印来源（避免日志噪声）
            logger.info(
                f"[meta-client] init account_id={account_id or '-'} token_source={token_source}"
            )

    @property
    def _client(self) -> httpx.AsyncClient:
        return _get_shared_client()

    def _add_token(self, params: dict | None) -> dict:
        params = params or {}
        params["access_token"] = self.access_token
        return params

    async def _handle_response(self, response: httpx.Response) -> dict:
        data = response.json()
        if "error" in data:
            err = data["error"]
            raise MetaApiError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown error"),
                fbtrace_id=err.get("fbtrace_id", ""),
                error_subcode=err.get("error_subcode", 0),
                error_user_msg=err.get("error_user_msg", ""),
            )
        response.raise_for_status()
        return data

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        self._check_endpoint(endpoint)
        parts = endpoint.strip('/').split('/')
        if len(parts) > 1 and parts[0].isdecimal() and parts[1] in ('ads', 'adsets', 'insights'):
            from core.isolation import check_entity
            check_entity('meta', 'adgroup' if parts[1] == 'ads' else 'campaign', parts[0])
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"META GET {url}")
        resp = await self._client.get(url, params=self._add_token(params))
        return await self._handle_response(resp)

    async def post(self, endpoint: str, payload: dict | None = None) -> dict:
        self._check_endpoint(endpoint)
        root = endpoint.strip('/').split('/')[0]
        if root.isdecimal():
            from core.isolation import check_entity
            from fastapi import HTTPException
            for level in ('campaign', 'adgroup', 'ad'):
                try:
                    check_entity('meta', level, root)
                    break
                except HTTPException:
                    continue
            else:
                raise HTTPException(403, '对象不属于当前租户或尚未同步')
        from services.launch_draft_service import checkpoint_call
        return await checkpoint_call('meta', endpoint, payload, lambda: self._post_unchecked(endpoint, dict(payload or {})))

    def _check_endpoint(self, endpoint):
        root = endpoint.strip('/').split('/')[0]
        if root.startswith('act_'):
            from services.credential_service import _check_account_scope
            from core.isolation import tenant_id
            _check_account_scope(tenant_id(), 'meta', root)

    async def _post_unchecked(self, endpoint: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"META POST {url}")
        payload = payload or {}
        payload["access_token"] = self.access_token
        resp = await self._client.post(url, data=payload)
        return await self._handle_response(resp)

    async def close(self):
        pass
