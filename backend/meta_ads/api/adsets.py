"""Meta 广告组 (Ad Set) 管理"""

from __future__ import annotations
from meta_ads.api.client import MetaClient
from core.isolation import default_account_id
from config import get_settings


class MetaAdSetService:
    def __init__(self, ad_account_id: str | None = None, client: MetaClient | None = None):
        self.ad_account_id = ad_account_id or default_account_id("meta")
        self.client = client or MetaClient(account_id=self.ad_account_id or None)

    async def list(self, campaign_id: str | None = None, limit: int = 50) -> dict:
        fields = "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,billing_event,bid_amount,targeting,created_time"
        if campaign_id:
            return await self.client.get(f"{campaign_id}/adsets", {"fields": fields, "limit": limit})
        return await self.client.get(f"{self.ad_account_id}/adsets", {"fields": fields, "limit": limit})

    async def create(self, data: dict) -> dict:
        return await self.client.post(f"{self.ad_account_id}/adsets", data)

    async def update(self, adset_id: str, data: dict) -> dict:
        return await self.client.post(adset_id, data)

    async def update_status(self, adset_id: str, status: str) -> dict:
        return await self.client.post(adset_id, {"status": status})
