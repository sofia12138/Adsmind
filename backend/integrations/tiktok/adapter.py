"""TikTok Ads 平台适配器 — 包装现有 tiktok_ads.api.campaign"""
from __future__ import annotations

from core.isolation import default_account_id
from config import get_settings
from integrations.base import BaseAdsAdapter
from schemas.campaign import CampaignDTO
from tiktok_ads.api.campaign import CampaignService as TikTokCampaignSvc


class TikTokAdsAdapter(BaseAdsAdapter):

    def __init__(self, advertiser_id: str | None = None):
        self.advertiser_id = advertiser_id or default_account_id("tiktok")
        self._svc = TikTokCampaignSvc(self.advertiser_id)

    async def list_campaigns(self, *, page: int = 1, page_size: int = 20,
                             filtering: dict | None = None, **kwargs) -> tuple[list[dict], list[CampaignDTO]]:
        raw = await self._svc.list(page=page, page_size=page_size, filtering=filtering)
        items = raw.get("list", [])
        normalized = [self._to_dto(c) for c in items]
        return items, normalized

    async def update_campaign_status(self, campaign_ids: list[str], status: str, **kwargs) -> dict:
        return await self._svc.update_status(campaign_ids, status)

    @staticmethod
    def _to_dto(c: dict) -> CampaignDTO:
        return CampaignDTO(
            id=str(c.get("campaign_id", "")),
            name=c.get("campaign_name", ""),
            status=c.get("operation_status", c.get("secondary_status", "")),
            platform="tiktok",
            spend=None,
            impressions=None,
            clicks=None,
            conversions=None,
            revenue=None,
            roi=None,
        )
