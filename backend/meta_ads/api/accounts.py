"""Meta 广告账户管理"""

from __future__ import annotations
from meta_ads.api.client import MetaClient
from core.isolation import default_account_id
from config import get_settings


class MetaAccountService:
    def __init__(self, client: MetaClient | None = None):
        self.client = client or MetaClient()

    async def list_accounts(self) -> dict:
        """获取当前用户有权限的所有广告账户"""
        params = {
            "fields": "account_id,name,account_status,currency,timezone_name,amount_spent",
            "limit": 100,
        }
        return await self.client.get("me/adaccounts", params)

    async def get_account_info(self, ad_account_id: str | None = None) -> dict:
        account_id = ad_account_id or default_account_id("meta")
        params = {
            "fields": "account_id,name,account_status,currency,timezone_name,amount_spent,balance",
        }
        return await self.client.get(account_id, params)
