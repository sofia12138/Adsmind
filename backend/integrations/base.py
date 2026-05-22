"""平台适配器抽象基类 + 工厂函数。

阶段 2 起追加 OAuth flow 工厂 `get_oauth_flow(platform)`，统一对接 oauth_base.OAuthFlow。
阶段 4 将把 BaseAdsAdapter 重写为完整接口（list/create/update/insights/upload），
当前保持薄抽象以避免破坏现有 routes/repositories。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from schemas.campaign import CampaignDTO


class BaseAdsAdapter(ABC):
    """所有广告平台适配器的基类。本轮只覆盖 campaign list + status。"""

    @abstractmethod
    async def list_campaigns(self, **kwargs) -> tuple[list[dict], list[CampaignDTO]]:
        """返回 (原始平台数据列表, 标准化 DTO 列表)"""
        ...

    @abstractmethod
    async def update_campaign_status(self, campaign_ids: list[str], status: str, **kwargs) -> dict:
        """更新 campaign 状态，返回平台原始响应"""
        ...


def get_ads_adapter(platform: str, advertiser_id: str | None = None) -> BaseAdsAdapter:
    """根据平台标识返回对应的适配器实例"""
    if platform == "tiktok":
        from integrations.tiktok.adapter import TikTokAdsAdapter
        return TikTokAdsAdapter(advertiser_id=advertiser_id)
    elif platform == "meta":
        from integrations.meta.adapter import MetaAdsAdapter
        return MetaAdsAdapter(ad_account_id=advertiser_id)
    else:
        raise ValueError(f"不支持的广告平台: {platform}")


# ── OAuth Flow 工厂（阶段 2 新增） ────────────────────────────────

_OAUTH_REGISTRY: dict[str, type] = {}


def register_oauth_flow(platform: str, cls: type) -> None:
    """显式注册某个平台的 OAuthFlow 实现。后续平台扩展只需调用这一行。"""
    _OAUTH_REGISTRY[platform] = cls


def get_oauth_flow(platform: str):
    """根据平台标识返回 OAuthFlow 实例。

    内置 tiktok / meta；其他平台（google / oceanengine / snapchat）
    将在阶段 4 通过 `register_oauth_flow()` 注册。
    """
    if platform in _OAUTH_REGISTRY:
        return _OAUTH_REGISTRY[platform]()
    if platform == "tiktok":
        from integrations.tiktok.oauth import TikTokOAuth
        return TikTokOAuth()
    if platform == "meta":
        from integrations.meta.oauth import MetaOAuth
        return MetaOAuth()
    raise ValueError(f"不支持的 OAuth 平台: {platform}")


def supported_oauth_platforms() -> list[str]:
    builtin = ["tiktok", "meta"]
    return list(dict.fromkeys(builtin + list(_OAUTH_REGISTRY.keys())))
