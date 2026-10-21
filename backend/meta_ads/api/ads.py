"""Meta 广告管理"""

from __future__ import annotations
from meta_ads.api.client import MetaClient
from core.isolation import default_account_id
from config import get_settings


class MetaAdService:
    def __init__(self, ad_account_id: str | None = None, client: MetaClient | None = None):
        self.ad_account_id = ad_account_id or default_account_id("meta")
        self.client = client or MetaClient(account_id=self.ad_account_id or None)

    async def list(self, adset_id: str | None = None, limit: int = 50) -> dict:
        fields = "id,name,adset_id,campaign_id,status,effective_status,creative,created_time,updated_time"
        if adset_id:
            return await self.client.get(f"{adset_id}/ads", {"fields": fields, "limit": limit})
        return await self.client.get(f"{self.ad_account_id}/ads", {"fields": fields, "limit": limit})

    async def create(self, data: dict) -> dict:
        return await self.client.post(f"{self.ad_account_id}/ads", data)

    async def update(self, ad_id: str, data: dict) -> dict:
        return await self.client.post(ad_id, data)

    async def update_status(self, ad_id: str, status: str) -> dict:
        return await self.client.post(ad_id, {"status": status})
