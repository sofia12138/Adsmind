"""广告管理"""

from __future__ import annotations
from tiktok_ads.api.client import TikTokClient
from tiktok_ads.models.ad import AdCreate, AdUpdate
from core.isolation import default_account_id
from config import get_settings


class AdService:
    def __init__(self, advertiser_id: str | None = None, client: TikTokClient | None = None):
        self.advertiser_id = advertiser_id or default_account_id("tiktok")
        self.client = client or TikTokClient(account_id=self.advertiser_id or None)

    async def create(self, ad: AdCreate) -> dict:
        payload = {"advertiser_id": self.advertiser_id, **ad.model_dump(exclude_none=True)}
        return await self.client.post("ad/create/", payload)

    async def update(self, ad: AdUpdate) -> dict:
        payload = {"advertiser_id": self.advertiser_id, **ad.model_dump(exclude_none=True)}
        return await self.client.post("ad/update/", payload)

    async def list(self, adgroup_ids: list[str] | None = None, page: int = 1, page_size: int = 20, filtering: dict | None = None) -> dict:
        params = {"advertiser_id": self.advertiser_id, "page": page, "page_size": page_size}
        if adgroup_ids:
            import json
            params["filtering"] = json.dumps({"adgroup_ids": adgroup_ids})
        elif filtering:
            import json
            params["filtering"] = json.dumps(filtering)
        return await self.client.get("ad/get/", params)

    async def update_status(self, ad_ids: list[str], status: str) -> dict:
        payload = {"advertiser_id": self.advertiser_id, "ad_ids": ad_ids, "operation_status": status}
        return await self.client.post("ad/status/update/", payload)
