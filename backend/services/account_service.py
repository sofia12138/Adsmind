"""广告账户管理服务层"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from repositories import biz_account_repository

_MASK_KEEP = 6


def _mask(token: str | None) -> str:
    if not token:
        return ""
    if len(token) <= _MASK_KEEP * 2:
        return "***"
    return token[:_MASK_KEEP] + "***" + token[-_MASK_KEEP:]


def _serialize(row: dict) -> dict:
    """将数据库行序列化为 API 返回格式，凭证脱敏"""
    out = dict(row)
    out["access_token_masked"] = _mask(out.pop("access_token", None))
    out["app_secret_masked"] = _mask(out.pop("app_secret", None))
    for k in ("created_at", "updated_at", "last_synced_at"):
        if out.get(k) and isinstance(out[k], datetime):
            out[k] = out[k].strftime("%Y-%m-%d %H:%M:%S")
    return out


def list_accounts(
    platform: str | None = None,
    application_id: int | None = None,
) -> list[dict]:
    """列出广告账号。

    `application_id` 阶段 4 X3-filter：
      - None       → 全租户视角（默认应用/旧调用方）
      - 非 None    → 严格按应用过滤
    """
    if platform:
        rows = biz_account_repository.list_by_platform(platform, application_id=application_id)
    else:
        rows = biz_account_repository.list_all(application_id=application_id)
    return [_serialize(r) for r in rows]


def get_account(row_id: int) -> dict | None:
    row = biz_account_repository.get_by_id(row_id)
    return _serialize(row) if row else None


async def verify_token(platform: str, access_token: str,
                       app_id: str = "", app_secret: str = "") -> dict[str, Any]:
    """调用平台 API 验证 Token 有效性，返回可用的账户列表"""
    if platform == "tiktok":
        return await _verify_tiktok(access_token, app_id, app_secret)
    elif platform == "meta":
        return await _verify_meta(access_token)
    else:
        raise ValueError(f"不支持的平台: {platform}")


async def _verify_tiktok(access_token: str, app_id: str, app_secret: str) -> dict:
    from tiktok_ads.api.client import TikTokClient, _get_shared_client
    import httpx

    settings_mod = __import__("config", fromlist=["get_settings"])
    settings = settings_mod.get_settings()

    url = f"{settings.tiktok_api_base_url}/oauth2/advertiser/get/"
    headers = {"Access-Token": access_token, "Content-Type": "application/json"}
    params = {"app_id": app_id or settings.tiktok_app_id,
              "secret": app_secret or settings.tiktok_app_secret}

    client = _get_shared_client()
    resp = await client.get(url, headers=headers, params=params)
    data = resp.json()

    if data.get("code") != 0:
        return {"valid": False, "error": data.get("message", "Token 验证失败"), "accounts": []}

    adv_list = data.get("data", {}).get("list", [])
    accounts = []
    for a in adv_list:
        accounts.append({
            "account_id": str(a.get("advertiser_id", "")),
            "account_name": a.get("advertiser_name", ""),
            "status": a.get("status", ""),
        })
    return {"valid": True, "accounts": accounts}


async def _verify_meta(access_token: str) -> dict:
    from meta_ads.api.client import MetaClient

    client = MetaClient(access_token=access_token)
    try:
        resp = await client.get("me/adaccounts", {
            "fields": "account_id,name,account_status,currency,timezone_name",
            "limit": 100,
        })
        acct_list = resp.get("data", [])
        accounts = []
        for a in acct_list:
            accounts.append({
                "account_id": a.get("id", a.get("account_id", "")),
                "account_name": a.get("name", ""),
                "currency": a.get("currency", "USD"),
                "timezone": a.get("timezone_name", ""),
                "status": "ACTIVE" if a.get("account_status") == 1 else "DISABLED",
            })
        return {"valid": True, "accounts": accounts}
    except Exception as e:
        return {"valid": False, "error": str(e), "accounts": []}


def add_account(*, platform: str, account_id: str, account_name: str = "",
                access_token: str, app_id: str = "", app_secret: str = "",
                currency: str = "USD", timezone: str = "UTC",
                application_id: int | None = None) -> dict:
    """新增广告账号。

    `application_id` 阶段 4 X3-filter：传入时新账号自动绑定到该应用。
    若未传，binding 在 biz_account_repository 层保留 NULL，由迁移 003 兜底到 default。
    """
    if platform not in ("tiktok", "meta"):
        raise ValueError("platform 必须为 tiktok 或 meta")
    if not account_id or not access_token:
        raise ValueError("account_id 和 access_token 不能为空")

    existing = biz_account_repository.list_by_platform(platform)
    is_default = 1 if len(existing) == 0 else 0

    biz_account_repository.upsert(
        platform=platform,
        account_id=account_id,
        account_name=account_name,
        access_token=access_token,
        app_id=app_id,
        app_secret=app_secret,
        currency=currency,
        timezone=timezone,
        status="ACTIVE",
        is_default=is_default,
    )
    row = biz_account_repository.get_by_platform_account(platform, account_id)

    # 创建后立即绑定到目标应用（如果传了）
    if row and application_id is not None:
        biz_account_repository.bind_to_application(int(row["id"]), application_id)
        row = biz_account_repository.get_by_id(int(row["id"]))

    logger.info(
        f"账户已添加: platform={platform}, account_id={account_id}, "
        f"application_id={application_id}"
    )
    return _serialize(row) if row else {}


def update_account(row_id: int, **fields) -> dict | None:
    biz_account_repository.update_by_id(row_id, **fields)
    row = biz_account_repository.get_by_id(row_id)
    return _serialize(row) if row else None


def delete_account(row_id: int) -> bool:
    return biz_account_repository.delete_by_id(row_id) > 0


def set_default_account(row_id: int) -> dict | None:
    row = biz_account_repository.get_by_id(row_id)
    if not row:
        raise KeyError(f"账户不存在: id={row_id}")
    biz_account_repository.set_default(row["platform"], row_id)
    row = biz_account_repository.get_by_id(row_id)
    return _serialize(row) if row else None


def seed_from_env() -> None:
    """从 .env 配置种子化默认账户（幂等）"""
    from config import get_settings
    settings = get_settings()

    if settings.tiktok_advertiser_id and settings.tiktok_access_token:
        existing = biz_account_repository.get_by_platform_account("tiktok", settings.tiktok_advertiser_id)
        if not existing:
            biz_account_repository.upsert(
                platform="tiktok",
                account_id=settings.tiktok_advertiser_id,
                account_name="默认 TikTok 广告主",
                access_token=settings.tiktok_access_token,
                app_id=settings.tiktok_app_id,
                app_secret=settings.tiktok_app_secret,
                is_default=1,
                status="ACTIVE",
            )
            logger.info(f"从 .env 种子化 TikTok 默认账户: {settings.tiktok_advertiser_id}")

    if settings.meta_ad_account_id and settings.meta_access_token:
        existing = biz_account_repository.get_by_platform_account("meta", settings.meta_ad_account_id)
        if not existing:
            biz_account_repository.upsert(
                platform="meta",
                account_id=settings.meta_ad_account_id,
                account_name="默认 Meta 广告账户",
                access_token=settings.meta_access_token,
                is_default=1,
                status="ACTIVE",
            )
            logger.info(f"从 .env 种子化 Meta 默认账户: {settings.meta_ad_account_id}")
