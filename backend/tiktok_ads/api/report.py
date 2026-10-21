"""数据报表"""

from __future__ import annotations
import json
from tiktok_ads.api.client import TikTokClient
from core.isolation import default_account_id
from config import get_settings


class ReportService:
    def __init__(self, advertiser_id: str | None = None, client: TikTokClient | None = None):
        self.advertiser_id = advertiser_id or default_account_id("tiktok")
        self.client = client or TikTokClient(account_id=self.advertiser_id or None)

    async def get_campaign_report(self, start_date: str, end_date: str, metrics: list[str] | None = None, page: int = 1, page_size: int = 20) -> dict:
        if metrics is None:
            metrics = ["spend", "impressions", "clicks", "ctr", "cpc", "cpm", "reach", "frequency", "complete_payment", "total_complete_payment_rate"]
        params = {
            "advertiser_id": self.advertiser_id, "report_type": "BASIC", "data_level": "AUCTION_CAMPAIGN",
            "dimensions": json.dumps(["campaign_id"]), "metrics": json.dumps(metrics),
            "start_date": start_date, "end_date": end_date, "page": page, "page_size": page_size,
        }
        return await self.client.get("report/integrated/get/", params)

    async def get_adgroup_report(self, start_date: str, end_date: str, metrics: list[str] | None = None, page: int = 1, page_size: int = 20) -> dict:
        if metrics is None:
            metrics = ["spend", "impressions", "clicks", "ctr", "cpc", "cpm", "complete_payment", "total_complete_payment_rate"]
        params = {
            "advertiser_id": self.advertiser_id, "report_type": "BASIC", "data_level": "AUCTION_ADGROUP",
            "dimensions": json.dumps(["adgroup_id"]), "metrics": json.dumps(metrics),
            "start_date": start_date, "end_date": end_date, "page": page, "page_size": page_size,
        }
        return await self.client.get("report/integrated/get/", params)

    async def get_ad_report(self, start_date: str, end_date: str, metrics: list[str] | None = None, page: int = 1, page_size: int = 20) -> dict:
        if metrics is None:
            metrics = ["spend", "impressions", "clicks", "ctr", "cpc", "cpm", "complete_payment", "total_complete_payment_rate"]
        params = {
            "advertiser_id": self.advertiser_id, "report_type": "BASIC", "data_level": "AUCTION_AD",
            "dimensions": json.dumps(["ad_id"]), "metrics": json.dumps(metrics),
            "start_date": start_date, "end_date": end_date, "page": page, "page_size": page_size,
        }
        return await self.client.get("report/integrated/get/", params)

    async def get_audience_report(self, start_date: str, end_date: str, dimensions: list[str] | None = None) -> dict:
        if dimensions is None:
            dimensions = ["age", "gender"]
        params = {
            "advertiser_id": self.advertiser_id, "report_type": "AUDIENCE", "data_level": "AUCTION_ADVERTISER",
            "dimensions": json.dumps(dimensions), "metrics": json.dumps(["spend", "impressions", "clicks", "ctr"]),
            "start_date": start_date, "end_date": end_date,
        }
        return await self.client.get("report/integrated/get/", params)
