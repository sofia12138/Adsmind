"""Meta Ads 平台适配器 — 包装现有 meta_ads.api.campaigns"""
from __future__ import annotations

from core.isolation import default_account_id
from config import get_settings
from integrations.base import BaseAdsAdapter
from schemas.campaign import CampaignDTO
from meta_ads.api.campaigns import MetaCampaignService as MetaCampaignSvc


class MetaAdsAdapter(BaseAdsAdapter):

    def __init__(self, ad_account_id: str | None = None):
        self.ad_account_id = ad_account_id or default_account_id("meta")
        self._svc = MetaCampaignSvc(self.ad_account_id)

    async def list_campaigns(self, *, limit: int = 50, **kwargs) -> tuple[list[dict], list[CampaignDTO]]:
        raw = await self._svc.list(limit=limit)
        items = raw.get("data", [])
        normalized = [self._to_dto(c) for c in items]
        return items, normalized

    async def update_campaign_status(self, campaign_ids: list[str], status: str, **kwargs) -> dict:
        results = {}
        for cid in campaign_ids:
            results[cid] = await self._svc.update_status(cid, status)
        return results

    @staticmethod
    def _to_dto(c: dict) -> CampaignDTO:
        budget = None
        if c.get("daily_budget"):
            budget = float(c["daily_budget"]) / 100
        elif c.get("lifetime_budget"):
            budget = float(c["lifetime_budget"]) / 100
        return CampaignDTO(
            id=str(c.get("id", "")),
            name=c.get("name", ""),
            status=c.get("effective_status", c.get("status", "")),
            platform="meta",
            spend=None,
            impressions=None,
            clicks=None,
            conversions=None,
            revenue=None,
            roi=None,
        )
