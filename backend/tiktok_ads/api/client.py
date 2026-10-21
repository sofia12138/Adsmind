"""TikTok Marketing API 基础 HTTP 客户端"""

import httpx
from loguru import logger
from config import get_settings

_shared_http: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """进程内复用的 AsyncClient，供直连完整 URL 的请求（如广告主列表）使用。"""
    global _shared_http
    if _shared_http is None:
        _shared_http = httpx.AsyncClient(timeout=30.0)
        logger.info(f"[tiktok-client] shared AsyncClient 初始化完成 (httpx={httpx.__version__})")
    return _shared_http


class TikTokApiError(Exception):
    def __init__(self, code: int, message: str, request_id: str = ""):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{code}] {message} (request_id={request_id})")


class TikTokClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        account_id: str | None = None,
        tenant_id: int | None = None,
    ):
        """构造 TikTok API 客户端。

        access_token 解析顺序（向后兼容）：
          1. 调用方显式传入的 `access_token`
          2. `services.credential_service.resolve_access_token()`：
             - 加密表 `app_oauth_credentials`
             - 旧明文 `biz_ad_accounts.access_token`
             - `.env` 默认 `TIKTOK_ACCESS_TOKEN`

        阶段 2 起推荐传 `account_id`（+ 可选 `tenant_id`），让 client 自动从
        加密表取 token；旧调用点不传 `access_token` 时也会走新路径，
        所以最终 token 来源会自动升级。
        """
        settings = get_settings()
        self.base_url = settings.tiktok_api_base_url
        if account_id:
            from services.credential_service import _check_account_scope
            from core.isolation import tenant_id as current_tenant_id
            _check_account_scope(tenant_id if tenant_id is not None else current_tenant_id(), 'tiktok', account_id)

        token = access_token
        token_source = "explicit" if token else "none"
        if not token:
            from services.credential_service import resolve_token_source
            token, token_source = resolve_token_source(
                "tiktok", account_id=account_id, tenant_id=tenant_id,
            )
        self.access_token = token or ""
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info(
            f"[tiktok-client] init base_url={self.base_url} "
            f"account_id={account_id or '-'} token_source={token_source}"
        )

    @property
    def _headers(self) -> dict:
        return {
            "Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    async def _handle_response(self, response: httpx.Response) -> dict | list:
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise TikTokApiError(
                code=data.get("code", -1),
                message=data.get("message", "Unknown error"),
                request_id=data.get("request_id", ""),
            )
        logger.debug(f"API OK: request_id={data.get('request_id')}")
        return data.get("data", {})

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        self._check_advertiser(params)
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"GET {url}")
        resp = await self._client.get(url, headers=self._headers, params=params)
        return await self._handle_response(resp)

    async def post(self, endpoint: str, payload: dict | None = None) -> dict:
        self._check_advertiser(payload)
        from services.launch_draft_service import checkpoint_call
        return await checkpoint_call('tiktok', endpoint, payload, lambda: self._post_unchecked(endpoint, dict(payload or {})))

    def _check_advertiser(self, body):
        aid = (body or {}).get('advertiser_id')
        if aid:
            from services.credential_service import _check_account_scope
            from core.isolation import tenant_id
            _check_account_scope(tenant_id(), 'tiktok', str(aid))

    async def _post_unchecked(self, endpoint: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"POST {url}")
        resp = await self._client.post(url, headers=self._headers, json=payload or {})
        return await self._handle_response(resp)

    async def close(self):
        await self._client.aclose()
