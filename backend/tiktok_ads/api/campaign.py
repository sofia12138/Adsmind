"""广告系列管理"""

from __future__ import annotations
from tiktok_ads.api.client import TikTokClient
from tiktok_ads.models.campaign import CampaignCreate, CampaignUpdate
from core.isolation import default_account_id
from config import get_settings


class CampaignService:
    def __init__(self, advertiser_id: str | None = None, client: TikTokClient | None = None):
        self.advertiser_id = advertiser_id or default_account_id("tiktok")
        self.client = client or TikTokClient(account_id=self.advertiser_id or None)

    async def create(self, campaign: CampaignCreate) -> dict:
        payload = {"advertiser_id": self.advertiser_id, **campaign.model_dump(exclude_none=True)}
        return await self.client.post("campaign/create/", payload)

    async def update(self, campaign: CampaignUpdate) -> dict:
        payload = {"advertiser_id": self.advertiser_id, **campaign.model_dump(exclude_none=True)}
        return await self.client.post("campaign/update/", payload)

    async def list(self, page: int = 1, page_size: int = 20, filtering: dict | None = None) -> dict:
        params = {"advertiser_id": self.advertiser_id, "page": page, "page_size": page_size}
        if filtering:
            import json
            params["filtering"] = json.dumps(filtering)
        return await self.client.get("campaign/get/", params)

    async def update_status(self, campaign_ids: list[str], status: str) -> dict:
        payload = {"advertiser_id": self.advertiser_id, "campaign_ids": campaign_ids, "operation_status": status}
        return await self.client.post("campaign/status/update/", payload)
