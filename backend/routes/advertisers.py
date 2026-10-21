"""广告主账户路由 — 复用全局 httpx 连接池

数据来源：
1. OAuth 授权列表 (`oauth2/advertiser/get/`) — token 授权时勾选过的广告主，作为兜底
2. Business Center 下属账号 (`bc/advertiser/get/`) — BC 中后续新加入的账号
按 advertiser_id 去重 union；BC 接口失败时静默降级（保留 OAuth 列表）并在响应里加 warning。
"""

from fastapi import APIRouter
from loguru import logger
from config import get_settings
from tiktok_ads.api.client import _get_shared_client

router = APIRouter(prefix="/advertisers", tags=["广告主"])


async def _fetch_oauth_advertisers(settings) -> list[dict]:
    url = f"{settings.tiktok_api_base_url}/oauth2/advertiser/get/"
    headers = {"Access-Token": settings.tiktok_access_token, "Content-Type": "application/json"}
    params = {"app_id": settings.tiktok_app_id, "secret": settings.tiktok_app_secret}
    client = _get_shared_client()
    r = await client.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("code") != 0:
        logger.warning(f"[advertisers][oauth] code={data.get('code')} msg={data.get('message')}")
        return []
    return list(data.get("data", {}).get("list", []) or [])


async def _fetch_bc_advertisers(settings, bc_id: str) -> list[dict]:
    """拉取某 BC 下所有广告主账号（asset_type=ADVERTISER），自动分页。

    使用 `/open_api/v1.3/bc/asset/get/` 接口；返回字段是 asset_id / asset_name，
    需要映射为 advertiser_id / advertiser_name 以与 OAuth 列表对齐。
    """
    url = f"{settings.tiktok_api_base_url}/bc/asset/get/"
    headers = {"Access-Token": settings.tiktok_access_token}
    client = _get_shared_client()
    out: list[dict] = []
    page = 1
    page_size = 50
    while True:
        params = {
            "bc_id": bc_id,
            "asset_type": "ADVERTISER",
            "page": page,
            "page_size": page_size,
        }
        r = await client.get(url, headers=headers, params=params)
        data = r.json()
        if data.get("code") != 0:
            logger.warning(
                f"[advertisers][bc] bc_id={bc_id} page={page} "
                f"code={data.get('code')} msg={data.get('message')}"
            )
            if page == 1:
                raise RuntimeError(f"BC API code={data.get('code')} msg={data.get('message')}")
            break
        chunk = list(data.get("data", {}).get("list", []) or [])
        for item in chunk:
            aid = str(item.get("asset_id") or item.get("advertiser_id") or "").strip()
            if not aid:
                continue
            name = item.get("asset_name") or item.get("advertiser_name") or ""
            out.append({
                "advertiser_id": aid,
                "advertiser_name": name,
                "_source": "bc",
            })
        page_info = data.get("data", {}).get("page_info") or {}
        total_page = int(page_info.get("total_page") or 1)
        if page >= total_page or len(chunk) < page_size:
            break
        page += 1
        if page > 50:
            logger.warning(f"[advertisers][bc] bc_id={bc_id} 分页超过 50 页，提前中止")
            break
    return out


@router.get("/")
async def list_advertisers():
    from repositories import biz_account_repository
    from core.isolation import application_id
    rows = biz_account_repository.list_by_platform('tiktok', application_id=application_id())
    return {"data": [{"advertiser_id": r['account_id'], "advertiser_name": r['account_name'], "currency": r['currency'], "timezone": r['timezone']} for r in rows]}
