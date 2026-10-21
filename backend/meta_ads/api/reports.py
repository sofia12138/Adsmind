"""Meta 数据报表"""

from __future__ import annotations
from meta_ads.api.client import MetaClient
from core.isolation import default_account_id
from config import get_settings


class MetaReportService:
    def __init__(self, ad_account_id: str | None = None, client: MetaClient | None = None):
        self.ad_account_id = ad_account_id or default_account_id("meta")
        self.client = client or MetaClient(account_id=self.ad_account_id or None)

    async def get_account_insights(self, start_date: str, end_date: str, level: str = "campaign", limit: int = 50) -> dict:
        params = {
            "fields": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,actions,cost_per_action_type",
            "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
            "level": level,
            "limit": limit,
        }
        return await self.client.get(f"{self.ad_account_id}/insights", params)

    async def get_campaign_insights(self, campaign_id: str, start_date: str, end_date: str) -> dict:
        params = {
            "fields": "spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,actions",
            "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        }
        return await self.client.get(f"{campaign_id}/insights", params)
