"""广告投放模板管理 + 基于模板创建广告（TikTok / Meta 双平台）"""
from __future__ import annotations

import json
from fastapi import APIRouter, Body, Depends, Query
from loguru import logger

from tiktok_ads.api.client import TikTokClient
from meta_ads.api.client import MetaClient
from meta_ads.api.campaigns import MetaCampaignService
from meta_ads.api.adsets import MetaAdSetService
from meta_ads.api.ads import MetaAdService
from services import template_service
from services.delivery_language import (
    DEFAULT_DELIVERY_LANGUAGE,
    DEFAULT_DELIVERY_LANGUAGES,
    DeliveryLanguageError,
    resolve_meta_locales,
    resolve_tiktok_languages,
    validate_selected as _validate_delivery_language,
)
from services.oplog_service import log_operation
from auth import get_current_user, User
from repositories import biz_account_repository

router = APIRouter(prefix="/templates", tags=["投放模板"])

# ── 内置默认模板（仅供 db.py migrate_json_data 初始化时引用）───

BUILTIN_TEMPLATES: list[dict] = [
    {
        "id": "tpl_tiktok_android_purchase",
        "name": "TikTok 安卓-付费版",
        "platform": "tiktok",
        "objective_type": "APP_PROMOTION",
        "app_promotion_type": "APP_INSTALL",
        "optimization_goal": "IN_APP_EVENT",
        "operating_system": "ANDROID",
        "age_min": 18,
        "deep_bid_type": "AEO",
        "billing_event": "OCPM",
        "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
        "budget_mode": "BUDGET_MODE_DYNAMIC_DAILY_BUDGET",
        "schedule_type": "SCHEDULE_FROM_NOW",
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-03-12T00:00:00",
    },
    {
        "id": "tpl_web_to_app",
        "name": "Web to App - 网页转化",
        "platform": "tiktok",
        "objective_type": "WEB_CONVERSIONS",
        "promotion_type": "WEBSITE",
        "optimization_goal": "CONVERT",
        "optimization_event": "SHOPPING",
        "billing_event": "OCPM",
        "bid_type": "BID_TYPE_NO_BID",
        "age_min": 18,
        "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
        "budget_mode": "BUDGET_MODE_DYNAMIC_DAILY_BUDGET",
        "schedule_type": "SCHEDULE_FROM_NOW",
        "pixel_id": "7591744906821959696",
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-03-13T12:00:00",
    },
    {
        "id": "tpl_miniapp_troas",
        "name": "小程序投放—TROAS",
        "platform": "tiktok",
        "objective_type": "APP_PROMOTION",
        "promotion_type": "MINI_APP",
        "optimization_goal": "VALUE",
        "optimization_event": "ACTIVE_PAY",
        "deep_bid_type": "VO_MIN_ROAS",
        "roas_bid": 0.9,
        "secondary_optimization_event": "PURCHASE_ROI",
        "billing_event": "OCPM",
        "bid_type": "BID_TYPE_NO_BID",
        "placement_type": "PLACEMENT_TYPE_NORMAL",
        "placements": ["PLACEMENT_TIKTOK"],
        "age_min": 18,
        "budget_mode": "BUDGET_MODE_DYNAMIC_DAILY_BUDGET",
        "schedule_type": "SCHEDULE_FROM_NOW",
        "vbo_window": "ZERO_DAY",
        "minis_id": "mnu8f8spjpxjy7oa",
        "app_id": "7613116626166104080",
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-03-13T20:30:00",
    },
    # ── TikTok Minis 系统母版（不可直接编辑/删除，可另存为）──
    # 默认值反提自已跑通广告链路：
    #   campaign_id=1863044185193761 / adgroup_id=1863044185193777
    # 仅保留"环境无关"的策略字段；
    # advertiser_id / identity / video / minis_id 等环境字段每次创建时由用户提供。
    {
        "id": "tpl_tiktok_minis_basic",
        "template_key": "tpl_tiktok_minis_basic",
        "name": "TikTok Minis 系统母版",
        "platform": "tiktok",
        "template_type": "tiktok_minis_basic",
        "is_system": True,
        "is_editable": False,
        "campaign": {
            # ─────────────────────────────────────────────────────────
            #  TikTok Minis Campaign 创建依赖广告主开通 Smart+ OpenAPI 写权限。
            #  申请之前 campaign/create/ 必报 [40002] Enter a valid Campaign Type。
            #  申请通过后，下面这套字段与源 campaign 1863044185193761 完全对齐：
            #    objective_type=APP_PROMOTION
            #    campaign_type=REGULAR_CAMPAIGN
            #    campaign_automation_type=UPGRADED_SMART_PLUS
            #    budget_mode=BUDGET_MODE_DYNAMIC_DAILY_BUDGET（Smart+ 唯一接受的预算模式）
            #  budget 金额从 payload 透传到 adgroup 层；campaign 层 budget 不传金额。
            # ─────────────────────────────────────────────────────────
            "objective_type": "APP_PROMOTION",
            "campaign_type": "REGULAR_CAMPAIGN",
            "campaign_automation_type": "UPGRADED_SMART_PLUS",
            "budget_mode": "BUDGET_MODE_DYNAMIC_DAILY_BUDGET",
            "operation_status": "ENABLE",
        },
        "adgroup": {
            "promotion_type": "MINI_APP",
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_TIKTOK"],
            "billing_event": "OCPM",
            "bid_type": "BID_TYPE_NO_BID",
            "optimization_goal": "VALUE",
            "optimization_event": "ACTIVE_PAY",
            "secondary_optimization_event": "PURCHASE_ROI",
            "deep_bid_type": "VO_MIN_ROAS",
            "vbo_window": "ZERO_DAY",
            "schedule_type": "SCHEDULE_FROM_NOW",
            "budget_mode": "BUDGET_MODE_DAY",
            "age_groups": ["AGE_18_24", "AGE_25_34", "AGE_35_44", "AGE_45_54", "AGE_55_100"],
            "gender": "GENDER_UNLIMITED",
            "languages": ["en"],
            "operating_systems": [],
            "skip_learning_phase": True,
            "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE",
            # 默认建议值，可被 payload.budget / payload.roas_bid 覆盖
            "default_budget": 50,
            "default_roas_bid": 0.8,
        },
        "ad": {
            "ad_format": "SINGLE_VIDEO",
        },
        # 业务线默认 minis（可在 payload 中覆盖）
        "defaults": {
            "app_id": "7613116626166104080",
            "minis_id": "mnu8f8spjpxjy7oa",
            # 发单时仍以 location_ids 为准；location_selection 是结构化记录，
            # 用于前端按"国家代码 + 地区组"回显选择器，二者并存以兼容老数据。
            "location_ids": ["2077456", "2635167", "2186224", "6251999"],
            "location_selection": {
                "group_key": "tier1",
                "country_codes": ["US", "GB", "CA", "AU"],
            },
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-22T00:00:00",
    },
    # ──────────────────────────────────────────────────────────
    #  TikTok Web to App 系统母版（只读，可另存为）
    #  · source_ids 指向已跑通广告链：
    #      advertiser_id=7483423834243366928
    #      campaign_id=1856089130041841
    #      adgroup_id=1856089495835090
    #      ad_id=7602545102489210123
    #  · defaults 为母版快照；发单时只允许 editable_fields 白名单字段从 payload 覆盖
    #  · defaults 首次固化的初始值参考 tpl_web_to_app 旧系统模板 + TikTok W2A 通用默认
    #    后续可通过 GET /api/templates/system/tiktok-w2a/probe 从源链路重新抽取后替换
    # ──────────────────────────────────────────────────────────
    {
        "id": "tpl_tiktok_web_to_app_system",
        "template_key": "tpl_tiktok_web_to_app_system",
        "name": "TikTok Web to App 母版",
        "platform": "tiktok",
        "template_type": "tiktok_web_to_app",
        "is_system": True,
        "is_editable": False,
        "is_builtin": True,
        "created_by": "system",
        "source_ids": {
            "advertiser_id": "7483423834243366928",
            "campaign_id": "1856089130041841",
            "adgroup_id": "1856089495835090",
            "ad_id": "7602545102489210123",
        },
        # launch_from_template 直接读取 campaign/adgroup/ad 扁平节点，这里同时提供：
        "campaign": {
            "objective_type": "WEB_CONVERSIONS",
            "campaign_type": "REGULAR_CAMPAIGN",
            "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE",
        },
        "adgroup": {
            "promotion_type": "WEBSITE",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
            "placements": ["PLACEMENT_TIKTOK"],
            "billing_event": "OCPM",
            "bid_type": "BID_TYPE_NO_BID",
            "optimization_goal": "CONVERT",
            "optimization_event": "SHOPPING",
            "pacing": "PACING_MODE_SMOOTH",
            "schedule_type": "SCHEDULE_FROM_NOW",
            "budget_mode": "BUDGET_MODE_DAY",
            "operating_systems": [],
            "age_groups": ["AGE_18_24", "AGE_25_34", "AGE_35_44", "AGE_45_54", "AGE_55_100"],
            "gender": "GENDER_UNLIMITED",
            "languages": ["en"],
            "operation_status": "ENABLE",
            "default_budget": 50,
        },
        "ad": {
            "ad_format": "SINGLE_VIDEO",
            "call_to_action": "LEARN_MORE",
        },
        "defaults": {
            "objective_type": "WEB_CONVERSIONS",
            "campaign_budget_mode": "BUDGET_MODE_INFINITE",
            "campaign_status": "ENABLE",
            "adgroup_budget_mode": "BUDGET_MODE_DAY",
            "billing_event": "OCPM",
            "optimization_goal": "CONVERT",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
            "schedule_type": "SCHEDULE_FROM_NOW",
            "operating_system": [],
            "placement": {
                "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
                "placements": ["PLACEMENT_TIKTOK"],
            },
            "targeting": {
                "age_groups": ["AGE_18_24", "AGE_25_34", "AGE_35_44", "AGE_45_54", "AGE_55_100"],
                "gender": "GENDER_UNLIMITED",
                "languages": ["en"],
                "location_ids": ["2077456"],
                "location_selection": {
                    "group_key": "north_america",
                    "country_codes": ["US"],
                },
            },
            "identity": {
                "identity_type": "CUSTOMIZED_USER",
            },
            "tracking": {
                "pixel_id": "",
                "optimization_event": "SHOPPING",
                "tracking_url": "",
            },
            "creative_format": "SINGLE_VIDEO",
            "call_to_action": "LEARN_MORE",
            "landing_page_template": "",
        },
        "editable_fields": [
            "campaign_name",
            "adgroup_name",
            "ad_name",
            "budget",
            "bid",
            "country",
            "region_group",
            "age",
            "gender",
            "audience",
            "landing_page_url",
            "tracking_params",
            "video_id",
            "ad_text",
            "ad_title",
            "call_to_action",
            "schedule",
        ],
        "launch_rules": {
            "create_campaign": True,
            "create_adgroup": True,
            "create_ad": True,
            "multi_adgroup_supported": False,
            "multi_creative_supported": False,
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-22T00:00:00",
    },
    {
        "id": "tpl_meta_us_aeo",
        "name": "Meta US AEO Basic",
        "platform": "meta",
        "campaign": {
            "objective": "OUTCOME_APP_PROMOTION",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        "adset": {
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "APP_INSTALLS",
            "daily_budget": 5000,
            "targeting": {
                "geo_locations": {"countries": ["US"]},
                "age_min": 18,
                "age_max": 65,
            },
            "promoted_object": {},
            "status": "PAUSED",
        },
        "creative": {
            "page_id": "",
            "primary_text": "",
            "headline": "",
            "description": "",
            "call_to_action": "INSTALL_NOW",
            "link": "",
            "image_hash": "",
            "video_id": "",
        },
        "ad": {
            "status": "PAUSED",
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-09T00:00:00",
    },
    {
        "id": "tpl_meta_web_to_app_basic_abo",
        "name": "Meta Web to App Basic (ABO)",
        "platform": "meta",
        "template_type": "web_to_app",
        "campaign": {
            "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        "adset": {
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LANDING_PAGE_VIEWS",
            "daily_budget": 5000,
            "status": "PAUSED",
            "targeting": {
                "geo_locations": {"countries": ["US"]},
                "age_min": 18,
                "age_max": 65,
            },
            "promoted_object": {
                "pixel_id": "",
                "custom_event_type": "",
            },
        },
        "creative": {
            "page_id": "",
            "primary_text": "Watch now on our site, then continue in the app.",
            "headline": "Start Watching Now",
            "description": "",
            "call_to_action": "LEARN_MORE",
            "link": "",
            "image_hash": "",
            "video_id": "",
        },
        "tracking": {
            "landing_page_url": "",
            "deep_link_url": "",
            "app_store_url": "",
            "fallback_url": "",
            "utm_source": "meta",
            "utm_campaign": "",
            "utm_content": "",
        },
        "ad": {
            "status": "PAUSED",
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-14T00:00:00",
    },
    {
        "id": "tpl_meta_web_to_app_conv_abo",
        "template_key": "tpl_meta_web_to_app_conv_abo",
        "name": "Meta Web to App Conversion (ABO)",
        "platform": "meta",
        "template_type": "web_to_app",
        "template_subtype": "conversion",
        # 与 TikTok Minis 母版统一归入「系统母版」分组，只读、可另存为。
        "is_system": True,
        "is_editable": False,
        "campaign": {
            "objective": "OUTCOME_SALES",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        "adset": {
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "daily_budget": 5000,
            "status": "PAUSED",
            "targeting": {
                "geo_locations": {"countries": ["US"]},
                "age_min": 18,
                "age_max": 65,
            },
            "promoted_object": {
                "pixel_id": "",
                "custom_event_type": "PURCHASE",
            },
        },
        "creative": {
            "page_id": "",
            "primary_text": "Watch now on our site, then continue in the app.",
            "headline": "Start Watching Now",
            "description": "",
            "call_to_action": "LEARN_MORE",
            "link": "",
            "image_hash": "",
            "video_id": "",
        },
        "tracking": {
            "landing_page_url": "",
            "deep_link_url": "",
            "app_store_url": "",
            "fallback_url": "",
            "utm_source": "meta",
            "utm_campaign": "",
            "utm_content": "",
        },
        "ad": {
            "status": "PAUSED",
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-14T12:00:00",
    },
    {
        # ── Meta Web to App Conversion (CBO) ──
        # 与 ABO 仅一处差异：预算放在 Campaign 层（is_adset_budget_sharing_enabled=true）
        # AdSet 层不带 daily_budget / lifetime_budget。其他字段全部沿用 ABO。
        "id": "tpl_meta_web_to_app_conv_cbo",
        "template_key": "tpl_meta_web_to_app_conv_cbo",
        "name": "Meta Web to App Conversion (CBO)",
        "platform": "meta",
        "template_type": "web_to_app_conversion_cbo",
        "template_subtype": "conversion_cbo",
        "is_system": True,
        "is_editable": False,
        "campaign": {
            "objective": "OUTCOME_SALES",
            "status": "PAUSED",
            "special_ad_categories": [],
            # CBO（新版 Meta ACB）：仅靠 Campaign 层 daily_budget 触发系列预算优化；
            # 不要传 is_adset_budget_sharing_enabled，否则触发 [100] subcode=4834002。
            "daily_budget": 5000,
        },
        "adset": {
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            # CBO 模板下，daily_budget / lifetime_budget 不会进入 AdSet payload（由 _launch_meta 强制清理）
            # bid_strategy 也由 _launch_meta 强制为 LOWEST_COST_WITHOUT_CAP，避免 [100] subcode=1815857（缺少 bid_amount）
            "status": "PAUSED",
            "targeting": {
                "geo_locations": {"countries": ["US"]},
                "age_min": 18,
                "age_max": 65,
            },
            "promoted_object": {
                "pixel_id": "",
                "custom_event_type": "PURCHASE",
            },
        },
        "creative": {
            "page_id": "",
            "primary_text": "Watch now on our site, then continue in the app.",
            "headline": "Start Watching Now",
            "description": "",
            "call_to_action": "LEARN_MORE",
            "link": "",
            "image_hash": "",
            "video_id": "",
        },
        "tracking": {
            "landing_page_url": "",
            "deep_link_url": "",
            "app_store_url": "",
            "fallback_url": "",
            "utm_source": "meta",
            "utm_campaign": "",
            "utm_content": "",
        },
        "ad": {
            "status": "PAUSED",
        },
        "delivery_languages": ["en"],
        "default_delivery_language": "en",
        "created_at": "2026-04-24T00:00:00",
    },
]


# ── CRUD ──────────────────────────────────────────────────

@router.get("/")
async def list_templates():
    return {"data": template_service.list_templates()}


@router.get("/{tpl_id}")
async def get_template(tpl_id: str):
    t = template_service.get_template(tpl_id)
    if not t:
        return {"error": "模板不存在"}
    return {"data": t}


@router.post("/")
async def create_template(tpl: dict = Body(...), user: User = Depends(get_current_user)):
    result = template_service.create_template(tpl)
    log_operation(
        username=user.username,
        action="创建模板",
        target_type="template",
        target_id=result.get("id", ""),
        platform=result.get("platform", ""),
        after_data=_tpl_summary(result),
        error_message=f"创建模板: {result.get('name', '')} ({result.get('platform', '')})",
    )
    return {"data": result}


@router.put("/{tpl_id}")
async def update_template(tpl_id: str, tpl: dict = Body(...), user: User = Depends(get_current_user)):
    old = template_service.get_template(tpl_id)
    if not old:
        return {"error": "模板不存在"}
    if old.get("is_system") and not old.get("is_editable", True):
        return {"error": "系统母版不允许直接编辑，请使用「另存为」创建副本后修改"}
    result = template_service.update_template(tpl_id, tpl)
    if not result:
        return {"error": "模板不存在或不可编辑"}

    changed = _diff_fields(old, result)
    detail = f"changed_fields: {', '.join(changed)}" if changed else "无字段变更"
    log_operation(
        username=user.username,
        action="更新模板",
        target_type="template",
        target_id=tpl_id,
        platform=result.get("platform", ""),
        before_data=_tpl_summary(old),
        after_data=_tpl_summary(result),
        error_message=detail,
    )
    return {"data": result}


@router.delete("/{tpl_id}")
async def delete_template(tpl_id: str, user: User = Depends(get_current_user)):
    _builtin_ids = {t["id"] for t in BUILTIN_TEMPLATES}
    if tpl_id in _builtin_ids:
        return {"error": "系统内置模板不可删除"}
    old = template_service.get_template(tpl_id)
    if not old:
        return {"error": "模板不存在"}
    if old.get("is_system"):
        return {"error": "系统母版不可删除"}
    template_service.delete_template(tpl_id)
    log_operation(
        username=user.username,
        action="删除模板",
        target_type="template",
        target_id=tpl_id,
        platform=old.get("platform", "") if old else "",
        before_data=_tpl_summary(old) if old else None,
        error_message=f"删除模板: {old.get('name', tpl_id) if old else tpl_id}",
    )
    return {"message": "ok"}


@router.post("/{tpl_id}/clone")
async def clone_template(tpl_id: str, body: dict = Body(...), user: User = Depends(get_current_user)):
    """从现有模板另存为一个新业务模板副本"""
    source = template_service.get_template(tpl_id)
    if not source:
        return {"error": "源模板不存在"}

    new_name = body.get("name", "").strip()
    if not new_name:
        return {"error": "新模板名称不能为空"}

    clone_data = {k: v for k, v in source.items()
                  if k not in ("id", "name", "created_at", "updated_at",
                               "is_builtin", "is_system", "is_editable",
                               "template_key", "parent_template_id")}
    clone_data["name"] = new_name
    clone_data["parent_template_id"] = source.get("id", "")
    if body.get("notes"):
        clone_data["notes"] = body["notes"]

    result = template_service.create_template(clone_data)

    log_operation(
        username=user.username,
        action="另存为模板",
        target_type="template",
        target_id=result.get("id", ""),
        platform=result.get("platform", ""),
        after_data={
            "source_template_id": tpl_id,
            "new_template_id": result.get("id", ""),
            "new_name": new_name,
            "template_type": result.get("template_type", ""),
            "platform": result.get("platform", ""),
        },
        error_message=f"另存为模板: {new_name} (来源: {source.get('name', tpl_id)})",
    )
    return {"data": result}


# ── 基于模板创建广告（平台分流）────────────────────────────

@router.post("/launch")
async def launch_from_template(payload: dict = Body(...), _user: User = Depends(get_current_user)):
    """
    通用 payload:
      template_id       - 模板 tpl_id
      campaign_name     - 广告系列名称
      budget            - 预算金额 (USD)

    TikTok 额外字段:
      advertiser_id, budget_mode, location_ids, languages,
      placement_type, placements, ad_text, deeplink,
      app_id, identity_id, identity_type, creatives

    Meta 额外字段:
      ad_account_id     - Meta 广告账户 ID (必填, 如 act_123456)
      overrides         - 可选覆盖字段, 支持 campaign/adset/creative/ad 子节点
    """
    tpl_id = payload.get("template_id")
    tpl = template_service.get_template(tpl_id)
    if not tpl:
        return {"error": "模板不存在"}

    platform = tpl.get("platform", "tiktok")
    template_type = (tpl.get("template_type") or "").lower()
    logger.info(f"[launch] template_id={tpl_id}  platform={platform}  type={template_type}")

    # ── 投放语种：模板默认 + 本次选择校验（强制开启，不允许跳过） ──
    allowed_langs = tpl.get("delivery_languages") or list(DEFAULT_DELIVERY_LANGUAGES)
    default_lang = tpl.get("default_delivery_language") or (
        allowed_langs[0] if allowed_langs else DEFAULT_DELIVERY_LANGUAGE
    )
    raw_selected = payload.get("selected_delivery_language") or default_lang
    try:
        selected_lang = _validate_delivery_language(raw_selected, allowed_langs)
    except DeliveryLanguageError as e:
        # 不进入下游 launch，直接以统一错误响应返回（同时仍写一次操作日志）
        resp = {"error": str(e)}
        _log_launch(_user, tpl_id, platform, payload, resp)
        return resp
    payload["selected_delivery_language"] = selected_lang
    payload["_delivery_language_allowed"] = list(allowed_langs)

    if platform == "meta":
        resp = await _launch_meta(tpl, payload)
    elif template_type == "tiktok_minis_basic":
        resp = await _launch_tiktok_minis(tpl, payload)
    elif template_type == "tiktok_web_to_app":
        resp = await _launch_tiktok_web_to_app(tpl, payload)
    else:
        resp = await _launch_tiktok(tpl, payload)

    _log_launch(_user, tpl_id, platform, payload, resp)
    return resp


# ══════════════════════════════════════════════════════════
#  Meta 模板投放
# ══════════════════════════════════════════════════════════

async def _launch_meta(tpl: dict, payload: dict) -> dict:
    tpl_id = tpl.get("id", "?")
    template_type = tpl.get("template_type", "")
    # CBO 判定：只看 template_type / id；和 ABO 唯一差异 = 预算层级
    is_cbo = (
        template_type == "web_to_app_conversion_cbo"
        or tpl_id == "tpl_meta_web_to_app_conv_cbo"
    )
    budget_mode = "CBO" if is_cbo else "ABO"
    ad_account_id = payload.get("ad_account_id", "").strip()
    if not ad_account_id:
        return {"error": "Meta 投放必须提供 ad_account_id（如 act_123456）"}

    campaign_name = payload.get("campaign_name", "")
    if not campaign_name:
        return {"error": "campaign_name 不能为空"}

    budget = float(payload.get("budget", 0))
    overrides = payload.get("overrides", {})
    materials: list[dict] = payload.get("materials", [])
    adsets_input: list[dict] = payload.get("adsets", [])
    # 投放时间（Meta W2A Conversion ABO 优化项）
    # 顶层 meta_schedule 优先；其次 overrides.adset.start_time/end_time
    meta_schedule = payload.get("meta_schedule") or {}
    schedule_start_time = (meta_schedule.get("start_time") or overrides.get("adset", {}).get("start_time") or "").strip() if isinstance(meta_schedule, dict) else ""
    schedule_end_time = (meta_schedule.get("end_time") or overrides.get("adset", {}).get("end_time") or "").strip() if isinstance(meta_schedule, dict) else ""
    schedule_timezone = (meta_schedule.get("timezone") or "").strip() if isinstance(meta_schedule, dict) else ""

    tpl_campaign = _deep_merge(tpl.get("campaign", {}), overrides.get("campaign", {}))
    tpl_adset = _deep_merge(tpl.get("adset", {}), overrides.get("adset", {}))
    tpl_creative = _deep_merge(tpl.get("creative", {}), overrides.get("creative", {}))
    tpl_tracking = _deep_merge(tpl.get("tracking", {}), overrides.get("tracking", {}))
    tpl_ad = _deep_merge(tpl.get("ad", {}), overrides.get("ad", {}))

    landing_url = tpl_tracking.get("landing_page_url", "")
    if landing_url and not tpl_creative.get("link"):
        tpl_creative["link"] = landing_url

    # ── 兼容旧结构：无 materials/adsets 时自动转换 ──
    if not materials and not adsets_input:
        image_hash = tpl_creative.get("image_hash", "")
        video_id = tpl_creative.get("video_id", "")
        if image_hash or video_id:
            mat_type = "video" if video_id else "image"
            materials = [{
                "id": "mat_legacy",
                "type": mat_type,
                "image_hash": image_hash,
                "video_id": video_id,
                "original_name": f"{campaign_name}_ad",
                "ad_name": f"{campaign_name}_ad",
            }]
        ov_adset = overrides.get("adset", {})
        targeting = ov_adset.get("targeting") or tpl_adset.get("targeting", {"geo_locations": {"countries": ["US"]}})
        po = ov_adset.get("promoted_object") or tpl_adset.get("promoted_object", {})
        daily_b = ov_adset.get("daily_budget") or tpl_adset.get("daily_budget", 5000)
        if budget:
            daily_b = int(budget * 100)
        adsets_input = [{
            "name": f"{campaign_name}",
            "daily_budget": daily_b,
            "targeting": targeting,
            "promoted_object": po,
            "material_ids": [m["id"] for m in materials],
        }]

    # ── 校验 ──
    if not materials:
        return {"error": "至少需要 1 个素材 (materials)"}
    if len(materials) > 20:
        return {"error": f"素材总数不能超过 20 个，当前 {len(materials)}"}
    if not adsets_input:
        return {"error": "至少需要 1 个 adset"}

    mat_map = {m["id"]: m for m in materials}
    for m in materials:
        if not m.get("image_hash") and not m.get("video_id"):
            return {"error": f"素材 {m.get('original_name', m.get('id'))} 缺少 image_hash 或 video_id"}
        if m.get("video_id") and not m.get("image_hash") and not m.get("picture_url") and m.get("id") != "mat_legacy":
            return {"error": f"视频素材 {m.get('original_name', m.get('id'))} 缺少封面图 (image_hash 或 picture_url)，"
                             f"Meta 要求视频广告必须提供封面图"}

    for i, a in enumerate(adsets_input):
        if not a.get("material_ids"):
            return {"error": f"adset #{i+1} ({a.get('name', '')}) 没有分配素材"}
        for mid in a["material_ids"]:
            if mid not in mat_map:
                return {"error": f"adset #{i+1} 引用了不存在的素材 ID: {mid}"}

    if template_type == "web_to_app":
        missing = []
        if not tpl_creative.get("page_id"):
            missing.append("page_id")
        if not tpl_creative.get("link"):
            missing.append("link")
        if not tpl_creative.get("primary_text"):
            missing.append("primary_text")
        if not tpl_creative.get("headline"):
            missing.append("headline")
        if missing:
            return {"error": f"Web-to-App 模板缺少必填字段: {', '.join(missing)}"}

    # ── 投放语种 → Meta locales（必须成功，否则直接退出） ──
    selected_lang = payload.get("selected_delivery_language") or DEFAULT_DELIVERY_LANGUAGE
    try:
        applied_locales = resolve_meta_locales(selected_lang)
    except DeliveryLanguageError as e:
        return {"error": str(e)}

    results: dict = {
        "platform": "meta",
        "template_type": template_type,
        "ad_account_id": ad_account_id,
        "campaign": None,
        "adsets": [],
        # 预算模式（供前端结果展示 + 操作日志用）
        "budget_mode": budget_mode,
        "campaign_daily_budget": None,
        "adset_daily_budget": None,
        "schedule": {
            "enabled": bool(schedule_start_time),
            "start_time": schedule_start_time or None,
            "end_time": schedule_end_time or None,
            "timezone": schedule_timezone or None,
        },
        # 投放语种（必填 + 平台已映射结果）
        "delivery_language": {
            "selected": selected_lang,
            "allowed": list(payload.get("_delivery_language_allowed") or []),
            "applied_meta_locales": list(applied_locales),
        },
    }

    # 获取账户专属 token（阶段 2：通过统一凭证服务，自动走加密表 → 兼容明文 → .env）
    from services.credential_service import resolve_token_source
    _acct_token, _acct_token_src = resolve_token_source("meta", account_id=ad_account_id)
    _acct_row = biz_account_repository.get_by_platform_account("meta", ad_account_id)
    _client = MetaClient(access_token=_acct_token, account_id=ad_account_id) if _acct_token else MetaClient()
    # 账户时区：当 meta_schedule.timezone 未指定时，作为时间字符串展示参考；
    # Meta API 接受 ISO 8601（如 2026-04-25T10:00:00-0700），前端必须把时间转成带偏移的 ISO 后下发，
    # 后端这里只做透传 + 日志，不做时区算术，避免歧义。
    _account_tz = (_acct_row or {}).get("timezone") or "UTC"
    logger.info(f"[launch-meta] token={_acct_token_src}  account={ad_account_id}  "
                f"budget_mode={budget_mode}  materials={len(materials)}  adsets={len(adsets_input)}  "
                f"schedule_start={schedule_start_time or '-'}  schedule_end={schedule_end_time or '-'}  "
                f"tz_input={schedule_timezone or '-'}  tz_account={_account_tz}")

    svc_campaign = MetaCampaignService(ad_account_id, client=_client)
    svc_adset = MetaAdSetService(ad_account_id, client=_client)
    svc_ad = MetaAdService(ad_account_id, client=_client)

    # ══ Step 1: Campaign ══
    # 预算模式：
    #   CBO → Campaign 层带 daily_budget；不传 is_adset_budget_sharing_enabled
    #         （Meta 新版 ACB 不接受该字段；传了会触发 subcode=4834002）
    #   ABO → 维持既有逻辑：is_adset_budget_sharing_enabled=false，Campaign 层不带 daily_budget
    campaign_payload: dict = {
        "name": campaign_name,
        "objective": tpl_campaign.get("objective", "OUTCOME_TRAFFIC"),
        "status": tpl_campaign.get("status", "PAUSED"),
        "special_ad_categories": json.dumps(tpl_campaign.get("special_ad_categories", [])),
    }
    # 透传可选 Campaign 字段（仅当模板有定义时）
    for opt_key in ("buying_type", "bid_strategy"):
        v = tpl_campaign.get(opt_key)
        if v:
            campaign_payload[opt_key] = v

    if is_cbo:
        # CBO：Campaign 层日预算（cents）；显式不带 is_adset_budget_sharing_enabled
        try:
            cbo_daily = int(tpl_campaign.get("daily_budget") or 0)
        except (TypeError, ValueError):
            cbo_daily = 0
        if cbo_daily <= 0:
            results["budget_mode"] = "CBO"
            results["requested_budget_mode"] = "CBO"
            results["actual_budget_mode"] = "CBO_FAILED"
            results["failed_step"] = "campaign"
            results["campaign"] = {
                "success": False,
                "error": "CBO 模板要求 Campaign Daily Budget > 0（单位：cents）",
            }
            return {"data": results}
        campaign_payload["daily_budget"] = cbo_daily
        # CBO 必须在 Campaign 层指定 bid_strategy；否则 Meta 会沿用旧默认（含 BID_CAP），
        # 导致 AdSet 创建时报 [100] subcode=1815857（缺少 bid_amount）。
        # 默认强制使用「最低成本，不设上限」；不传 bid_amount。
        campaign_payload["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
        # 防御：若任何上游误把这些字段塞进 campaign_payload，统一删除
        for k in ("is_adset_budget_sharing_enabled", "campaign_budget_optimization",
                  "budget_sharing", "bid_amount", "bid_cap", "target_cost", "cost_cap"):
            campaign_payload.pop(k, None)
        results["campaign_daily_budget"] = cbo_daily
        results["requested_budget_mode"] = "CBO"
    else:
        # ABO：保留既有 is_adset_budget_sharing_enabled=false 行为，不变
        campaign_payload["is_adset_budget_sharing_enabled"] = str(
            bool(tpl_campaign.get("is_adset_budget_sharing_enabled", False))
        ).lower()
    safe_cp = {k: v for k, v in campaign_payload.items() if k != "access_token"}
    if is_cbo:
        # CBO 调试日志：键集合 + 关键字段 + 是否带 access_token（不打印 token 本身）
        logger.info(
            "[launch-meta][cbo] campaign-debug "
            f"template_id={tpl_id} template_type={template_type} budget_mode=CBO "
            f"keys={sorted(campaign_payload.keys())} "
            f"daily_budget={campaign_payload.get('daily_budget')} "
            f"objective={campaign_payload.get('objective')} "
            f"bid_strategy={campaign_payload.get('bid_strategy')} "
            f"buying_type={campaign_payload.get('buying_type')} "
            f"status={campaign_payload.get('status')} "
            f"special_ad_categories={campaign_payload.get('special_ad_categories')} "
            f"has_is_adset_budget_sharing={'is_adset_budget_sharing_enabled' in campaign_payload} "
            f"has_bid_amount={'bid_amount' in campaign_payload} "
            f"has_access_token={bool(_acct_token or _client.access_token)}"
        )
    logger.info(f"[launch-meta] step=campaign  payload={safe_cp}")
    try:
        campaign_data = await svc_campaign.create(campaign_payload)
        campaign_id = campaign_data.get("id", "")
        results["campaign"] = {"success": True, "campaign_id": campaign_id}
        if is_cbo:
            results["actual_budget_mode"] = "CBO"
        logger.info(f"[launch-meta] Campaign 创建成功: {campaign_id}")
    except Exception as e:
        # 结构化错误信息：CBO 必须暴露 meta_error_code/subcode；不允许 fallback 到 ABO
        meta_code = getattr(e, "code", None)
        meta_subcode = getattr(e, "error_subcode", None)
        meta_message = getattr(e, "message", None) or str(e)
        # error 字段保证非空，否则前端只显示 "campaign创建失败:" 看不到原因
        _err_str = str(e).strip()
        if not _err_str:
            _err_str = (
                f"[{meta_code or '?'}] {meta_message or 'unknown Meta error'}"
                + (f" (subcode={meta_subcode})" if meta_subcode else "")
            )
        logger.error(
            f"[launch-meta] Campaign 创建失败: code={meta_code} subcode={meta_subcode} "
            f"message={meta_message!r}  raw={str(e)!r}  payload={safe_cp}"
        )
        camp_err: dict = {
            "success": False,
            "error": _err_str,
            "payload_sent": safe_cp,
            "meta_error_code": meta_code,
            "meta_error_subcode": meta_subcode,
            "meta_error_message": meta_message,
            "campaign_payload_debug": safe_cp,
        }
        results["campaign"] = camp_err
        results["failed_step"] = "campaign"
        if is_cbo:
            # CBO 失败 → 标记 CBO_FAILED，明确不会 fallback；前端展示红色错误
            results["actual_budget_mode"] = "CBO_FAILED"
        return {"data": results}

    # ══ Step 2+3: 遍历 adsets → 每个 adset 下创建 ads ══
    for idx, adset_cfg in enumerate(adsets_input):
        adset_name = adset_cfg.get("name") or f"{campaign_name}_{idx+1:02d}"
        adset_targeting = adset_cfg.get("targeting") or tpl_adset.get("targeting", {"geo_locations": {"countries": ["US"]}})
        # 强制注入语言定向：以 selected_delivery_language 映射结果为准，覆盖任何上游 locales。
        if isinstance(adset_targeting, dict):
            adset_targeting = {**adset_targeting, "locales": list(applied_locales)}
        adset_po = adset_cfg.get("promoted_object") or tpl_adset.get("promoted_object", {})
        opt_goal = tpl_adset.get("optimization_goal", "LANDING_PAGE_VIEWS")
        daily_budget = int(adset_cfg.get("daily_budget") or tpl_adset.get("daily_budget", 5000))

        adset_result: dict = {"adset_name": adset_name, "success": False, "ads": []}

        # bid_strategy 默认值：CBO 强制 LOWEST_COST_WITHOUT_CAP（即便模板/上游传了别的也覆盖）；
        # ABO 走原有兼容逻辑：模板有则用，没有则 LOWEST_COST_WITHOUT_CAP。
        if is_cbo:
            adset_bid_strategy = "LOWEST_COST_WITHOUT_CAP"
        else:
            adset_bid_strategy = tpl_adset.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"

        adset_payload = {
            "campaign_id": campaign_id,
            "name": adset_name,
            "status": tpl_adset.get("status", "PAUSED"),
            "billing_event": tpl_adset.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": opt_goal,
            "bid_strategy": adset_bid_strategy,
            "targeting": json.dumps(adset_targeting),
        }
        # 透传可选 AdSet 字段（注意：bid_amount 仅在非 CBO 下才允许）
        if not is_cbo:
            for opt_key in ("destination_type", "bid_amount"):
                v = tpl_adset.get(opt_key)
                if v:
                    adset_payload[opt_key] = v
            # 校验：若 bid_strategy 需要 bid_amount，必须提供且 > 0
            _need_bid_amount = adset_bid_strategy in ("LOWEST_COST_WITH_BID_CAP", "TARGET_COST", "COST_CAP")
            if _need_bid_amount:
                try:
                    _bid_amt = int(adset_payload.get("bid_amount") or 0)
                except (TypeError, ValueError):
                    _bid_amt = 0
                if _bid_amt <= 0:
                    adset_result["error"] = (
                        f"bid_strategy={adset_bid_strategy} 需要 bid_amount > 0（cents），当前未提供"
                    )
                    adset_result["meta_error_code"] = "VALIDATION"
                    results["adsets"].append(adset_result)
                    continue
        else:
            # CBO：仅透传 destination_type；显式不透传 bid_amount
            v = tpl_adset.get("destination_type")
            if v:
                adset_payload["destination_type"] = v

        if is_cbo:
            # CBO：AdSet 层禁止任何预算 / 共享 / 出价数额相关字段（防御性删除：哪怕模板/上游误塞也清掉）
            for k in ("daily_budget", "lifetime_budget", "budget", "is_adset_budget_sharing_enabled",
                      "bid_amount", "bid_cap", "target_cost", "cost_cap"):
                adset_payload.pop(k, None)
        else:
            # ABO：AdSet 层带 daily_budget
            adset_payload["daily_budget"] = daily_budget
            if results.get("adset_daily_budget") is None:
                results["adset_daily_budget"] = daily_budget
        po_valid = {k: v for k, v in adset_po.items() if v}
        if po_valid:
            adset_payload["promoted_object"] = json.dumps(po_valid)

        # 投放时间：start_time 必填则进 payload；end_time 选填，未填则视为长期投放
        # adset 级 schedule 优先级：adset_cfg > 顶层 meta_schedule
        as_start = (adset_cfg.get("start_time") or schedule_start_time or "").strip()
        as_end = (adset_cfg.get("end_time") or schedule_end_time or "").strip()
        if as_start:
            adset_payload["start_time"] = as_start
        if as_end:
            adset_payload["end_time"] = as_end

        safe_as = {k: v for k, v in adset_payload.items() if k != "access_token"}
        budget_log = (f"campaign_daily={results.get('campaign_daily_budget')} (CBO)" if is_cbo
                      else f"adset_daily={daily_budget} (ABO)")
        logger.info(f"[launch-meta] step=adset#{idx+1}  name={adset_name}  {budget_log}  payload={safe_as}")
        if is_cbo:
            # CBO AdSet 调试日志：必须保证不存在任何预算字段
            po_keys: list[str] = []
            try:
                po_raw = adset_payload.get("promoted_object")
                if isinstance(po_raw, str):
                    po_keys = list(json.loads(po_raw).keys())
                elif isinstance(po_raw, dict):
                    po_keys = list(po_raw.keys())
            except Exception:
                po_keys = []
            logger.info(
                f"[launch-meta][cbo] adset-debug#{idx+1} "
                f"keys={sorted(adset_payload.keys())} "
                f"bid_strategy={adset_payload.get('bid_strategy')} "
                f"has_bid_amount={'bid_amount' in adset_payload} "
                f"has_bid_cap={'bid_cap' in adset_payload} "
                f"has_target_cost={'target_cost' in adset_payload} "
                f"has_cost_cap={'cost_cap' in adset_payload} "
                f"has_daily_budget={'daily_budget' in adset_payload} "
                f"has_lifetime_budget={'lifetime_budget' in adset_payload} "
                f"optimization_goal={adset_payload.get('optimization_goal')} "
                f"billing_event={adset_payload.get('billing_event')} "
                f"destination_type={adset_payload.get('destination_type')} "
                f"promoted_object_keys={po_keys}"
            )

        try:
            adset_data = await svc_adset.create(adset_payload)
            adset_id = adset_data.get("id", "")
            adset_result["success"] = True
            adset_result["adset_id"] = adset_id
            logger.info(f"[launch-meta] AdSet#{idx+1} 创建成功: {adset_id}")
        except Exception as e:
            meta_code = getattr(e, "code", None)
            meta_subcode = getattr(e, "error_subcode", None)
            meta_message = getattr(e, "message", None) or str(e)
            _err_str = str(e).strip()
            if not _err_str:
                _err_str = (
                    f"[{meta_code or '?'}] {meta_message or 'unknown Meta error'}"
                    + (f" (subcode={meta_subcode})" if meta_subcode else "")
                )
            logger.error(
                f"[launch-meta] AdSet#{idx+1} 创建失败: code={meta_code} subcode={meta_subcode} "
                f"message={meta_message!r}  raw={str(e)!r}  payload={safe_as}"
            )
            adset_result["error"] = _err_str
            adset_result["payload_sent"] = safe_as
            adset_result["meta_error_code"] = meta_code
            adset_result["meta_error_subcode"] = meta_subcode
            adset_result["meta_error_message"] = meta_message
            if is_cbo:
                # CBO AdSet 失败 → 仅本 AdSet 失败，不切换到 ABO，不在 Campaign 层重试
                results["actual_budget_mode"] = "CBO_FAILED"
                if not results.get("failed_step"):
                    results["failed_step"] = "adset"
            results["adsets"].append(adset_result)
            continue

        # ── 为该 adset 创建 ads ──
        mat_ids = adset_cfg.get("material_ids", [])
        used_names: dict[str, int] = {}
        for mat_id in mat_ids:
            mat = mat_map.get(mat_id)
            if not mat:
                adset_result["ads"].append({"success": False, "material_id": mat_id, "error": "素材不存在"})
                continue

            ad_name = mat.get("ad_name", mat.get("original_name", mat_id))
            if len(adsets_input) > 1:
                ad_name = f"{ad_name}__{idx+1:02d}"
            if ad_name in used_names:
                used_names[ad_name] += 1
                ad_name = f"{ad_name}_{used_names[ad_name]}"
            else:
                used_names[ad_name] = 1

            mat_video = mat.get("video_id", "")
            mat_image = mat.get("image_hash", "")
            page_id = tpl_creative.get("page_id", "")
            link = tpl_creative.get("link", "")
            cta_block = {
                "type": tpl_creative.get("call_to_action", "LEARN_MORE"),
                "value": {"link": link},
            }

            mat_picture_url = mat.get("picture_url", "")

            story_spec: dict = {"page_id": page_id} if page_id else {}
            if mat_video:
                vdata: dict = {
                    "video_id": mat_video,
                    "message": tpl_creative.get("primary_text", ""),
                    "title": tpl_creative.get("headline", ""),
                    "link_description": tpl_creative.get("description", ""),
                    "call_to_action": cta_block,
                }
                if mat_image:
                    vdata["image_hash"] = mat_image
                elif mat_picture_url:
                    vdata["image_url"] = mat_picture_url
                    logger.info(f"[launch-meta] 使用自动封面 URL: ad_name={ad_name}")
                else:
                    logger.warning(
                        f"[launch-meta] 视频素材无封面图: ad_name={ad_name}, "
                        f"video_id={mat_video}, material={mat.get('original_name')}"
                    )
                story_spec["video_data"] = vdata
            elif mat_image:
                story_spec["link_data"] = {
                    "image_hash": mat_image,
                    "message": tpl_creative.get("primary_text", ""),
                    "name": tpl_creative.get("headline", ""),
                    "description": tpl_creative.get("description", ""),
                    "link": link,
                    "call_to_action": cta_block,
                }

            ad_payload = {
                "name": ad_name,
                "adset_id": adset_id,
                "status": tpl_ad.get("status", "PAUSED"),
                "creative": json.dumps({"object_story_spec": story_spec}),
            }

            ad_result: dict = {"ad_name": ad_name, "material_name": mat.get("original_name", ""), "material_type": mat.get("type", "")}
            logger.info(
                f"[launch-meta] step=ad  adset={adset_id}  adset_name={adset_name}  "
                f"ad_name={ad_name}  type={mat.get('type')}  "
                f"video_id={mat_video or 'N'}  image_hash={mat_image[:12] + '...' if mat_image else 'N'}"
            )
            try:
                ad_data = await svc_ad.create(ad_payload)
                ad_result["success"] = True
                ad_result["ad_id"] = ad_data.get("id", "")
                logger.info(f"[launch-meta] Ad 创建成功: {ad_result['ad_id']}  name={ad_name}")
            except Exception as e:
                logger.error(
                    f"[launch-meta] Ad 创建失败: {e}\n"
                    f"  adset_name={adset_name}, adset_id={adset_id}\n"
                    f"  material_name={mat.get('original_name')}, material_type={mat.get('type')}\n"
                    f"  video_id={mat_video}, image_hash={mat_image}\n"
                    f"  story_spec_keys={list(story_spec.keys())}"
                )
                ad_result["success"] = False
                ad_result["error"] = str(e)

            adset_result["ads"].append(ad_result)

        results["adsets"].append(adset_result)

    return {"data": results}


def _deep_merge(base: dict, overrides: dict) -> dict:
    """浅层合并 overrides 到 base 的副本，overrides 中非 None 的字段优先。"""
    merged = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        elif v is not None:
            merged[k] = v
    return merged


# ══════════════════════════════════════════════════════════
#  TikTok 模板投放（原逻辑保持不变）
# ══════════════════════════════════════════════════════════

async def _launch_tiktok(tpl: dict, payload: dict) -> dict:
    advertiser_id = payload.get("advertiser_id", "")
    campaign_name = payload.get("campaign_name", "")
    budget_mode_choice = payload.get("budget_mode", "ADGROUP")
    budget = float(payload.get("budget", 50))
    location_ids = payload.get("location_ids", [])
    # 投放语种（强制开启 → 用映射结果覆盖任何 payload.languages）
    selected_lang = payload.get("selected_delivery_language") or DEFAULT_DELIVERY_LANGUAGE
    try:
        languages = resolve_tiktok_languages(selected_lang)
    except DeliveryLanguageError as e:
        return {"error": str(e)}
    placement_type = payload.get("placement_type", tpl.get("placement_type", "PLACEMENT_TYPE_AUTOMATIC"))
    placements = payload.get("placements")
    schedule_type = payload.get("schedule_type", tpl.get("schedule_type", "SCHEDULE_FROM_NOW"))
    schedule_start_time = payload.get("schedule_start_time")
    schedule_end_time = payload.get("schedule_end_time")
    ad_text = payload.get("ad_text", "")
    deeplink = payload.get("deeplink", "")
    app_id = payload.get("app_id")
    identity_id = payload.get("identity_id")
    identity_type = payload.get("identity_type")
    creatives = payload.get("creatives", [])

    client = TikTokClient()
    results = {
        "platform": "tiktok",
        "campaign": None,
        "adgroup": None,
        "ads": [],
        "summary": {"total": 0, "success": 0, "fail": 0},
        "delivery_language": {
            "selected": selected_lang,
            "allowed": list(payload.get("_delivery_language_allowed") or []),
            "applied_tiktok_languages": list(languages),
        },
    }

    # ── 1. 创建 Campaign ──
    try:
        campaign_payload = {
            "advertiser_id": advertiser_id,
            "campaign_name": campaign_name,
            "objective_type": tpl.get("objective_type", "APP_PROMOTION"),
            "campaign_type": "REGULAR_CAMPAIGN",
            "operation_status": "ENABLE",
        }
        if tpl.get("app_promotion_type"):
            campaign_payload["app_promotion_type"] = tpl["app_promotion_type"]

        if budget_mode_choice == "CBO":
            campaign_payload["budget_mode"] = "BUDGET_MODE_DAY"
            campaign_payload["budget"] = budget
        else:
            campaign_payload["budget_mode"] = "BUDGET_MODE_INFINITE"

        campaign_data = await client.post("campaign/create/", campaign_payload)
        campaign_id = campaign_data.get("campaign_id") or campaign_data.get("campaign_ids", [""])[0]
        results["campaign"] = {"success": True, "campaign_id": campaign_id}
        logger.info(f"Campaign 创建成功: {campaign_id}")
    except Exception as e:
        logger.error(f"Campaign 创建失败: {e}")
        results["campaign"] = {"success": False, "error": str(e)}
        return {"data": results}

    # ── 2. 创建 Ad Group ──
    try:
        adgroup_payload: dict = {
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": campaign_name,
            "optimization_goal": tpl.get("optimization_goal", "IN_APP_EVENT"),
            "billing_event": tpl.get("billing_event", "OCPM"),
            "bid_type": tpl.get("bid_type", "BID_TYPE_NO_BID"),
            "placement_type": placement_type,
            "schedule_type": schedule_type,
            "operating_systems": [tpl.get("operating_system", "ANDROID")],
            "location_ids": location_ids,
            "operation_status": "ENABLE",
        }

        if tpl.get("secondary_optimization_event"):
            adgroup_payload["secondary_optimization_event"] = tpl["secondary_optimization_event"]

        if tpl.get("age_min"):
            adgroup_payload["age_groups"] = _age_groups_from_min(tpl["age_min"])

        # 强制语言定向：始终把 selected_delivery_language 映射结果写入 adgroup
        adgroup_payload["languages"] = list(languages)

        if placement_type == "PLACEMENT_TYPE_NORMAL" and placements:
            adgroup_payload["placements"] = placements

        if budget_mode_choice != "CBO":
            adgroup_payload["budget_mode"] = "BUDGET_MODE_DAY"
            adgroup_payload["budget"] = budget

        if schedule_start_time:
            adgroup_payload["schedule_start_time"] = schedule_start_time
        if schedule_end_time:
            adgroup_payload["schedule_end_time"] = schedule_end_time

        if app_id:
            adgroup_payload["app_id"] = app_id
            adgroup_payload["promotion_type"] = "APP_ANDROID"

        adgroup_data = await client.post("adgroup/create/", adgroup_payload)
        adgroup_id = adgroup_data.get("adgroup_id") or adgroup_data.get("adgroup_ids", [""])[0]
        results["adgroup"] = {"success": True, "adgroup_id": adgroup_id}
        logger.info(f"AdGroup 创建成功: {adgroup_id}")
    except Exception as e:
        logger.error(f"AdGroup 创建失败: {e}")
        results["adgroup"] = {"success": False, "error": str(e)}
        return {"data": results}

    # ── 3. 逐素材创建 Ad ──
    results["summary"]["total"] = len(creatives)
    for cr in creatives:
        ad_name = cr.get("name", "Ad")
        try:
            ad_payload: dict = {
                "advertiser_id": advertiser_id,
                "adgroup_id": adgroup_id,
                "ad_name": ad_name,
                "ad_text": ad_text,
                "ad_format": "SINGLE_VIDEO" if cr.get("video_id") else "SINGLE_IMAGE",
            }
            if cr.get("video_id"):
                ad_payload["video_id"] = cr["video_id"]
            if cr.get("image_id"):
                ad_payload["image_ids"] = [cr["image_id"]]

            if deeplink:
                ad_payload["deeplink"] = deeplink

            if identity_id:
                ad_payload["identity_id"] = identity_id
                ad_payload["identity_type"] = identity_type or "CUSTOMIZED_USER"

            ad_data = await client.post("ad/create/", ad_payload)
            ad_id = ad_data.get("ad_id") or ad_data.get("ad_ids", [""])[0]
            results["ads"].append({"ad_name": ad_name, "success": True, "ad_id": ad_id})
            results["summary"]["success"] += 1
            logger.info(f"Ad 创建成功: {ad_name} -> {ad_id}")
        except Exception as e:
            logger.error(f"Ad 创建失败 [{ad_name}]: {e}")
            results["ads"].append({"ad_name": ad_name, "success": False, "error": str(e)})
            results["summary"]["fail"] += 1

    return {"data": results}


# ══════════════════════════════════════════════════════════
#  TikTok Minis 系统母版投放（最小可用版本）
#  · 单 campaign / 单 adgroup / 单 ad / 单素材
#  · 模板提供策略默认值，环境字段必须由 payload 提供
# ══════════════════════════════════════════════════════════

async def _launch_tiktok_minis(tpl: dict, payload: dict) -> dict:
    tpl_campaign = dict(tpl.get("campaign", {}))
    tpl_adgroup = dict(tpl.get("adgroup", {}))
    tpl_ad = dict(tpl.get("ad", {}))
    tpl_defaults = dict(tpl.get("defaults", {}))

    advertiser_id = (payload.get("advertiser_id") or "").strip()
    campaign_name = (payload.get("campaign_name") or "").strip()
    adgroup_name = (payload.get("adgroup_name") or campaign_name or "").strip()
    ad_name = (payload.get("ad_name") or adgroup_name or "Ad").strip()

    if not advertiser_id:
        return {"error": "缺少 advertiser_id"}
    if not campaign_name:
        return {"error": "campaign_name 不能为空"}

    budget = float(payload.get("budget") or tpl_adgroup.get("default_budget") or 50)
    roas_bid = float(payload.get("roas_bid") or tpl_adgroup.get("default_roas_bid") or 0.8)

    location_ids = payload.get("location_ids") or tpl_defaults.get("location_ids") or []
    # 投放语种（强制开启）：忽略模板/payload 里的 languages，统一使用 selected_delivery_language 的映射
    selected_lang = payload.get("selected_delivery_language") or DEFAULT_DELIVERY_LANGUAGE
    try:
        languages = resolve_tiktok_languages(selected_lang)
    except DeliveryLanguageError as e:
        return {"error": str(e)}
    age_groups = payload.get("age_groups") or tpl_adgroup.get("age_groups") or []
    gender = payload.get("gender") or tpl_adgroup.get("gender") or "GENDER_UNLIMITED"

    schedule_start_time = payload.get("schedule_start_time")
    schedule_end_time = payload.get("schedule_end_time")
    schedule_type = payload.get("schedule_type") or tpl_adgroup.get(
        "schedule_type", "SCHEDULE_FROM_NOW"
    )

    app_id = payload.get("app_id") or tpl_defaults.get("app_id")
    minis_id = payload.get("minis_id") or tpl_defaults.get("minis_id")
    if not app_id or not minis_id:
        return {"error": "缺少 app_id 或 minis_id（小程序投放必填）"}

    identity_id = payload.get("identity_id")
    identity_type = payload.get("identity_type") or "CUSTOMIZED_USER"
    if not identity_id:
        return {"error": "缺少 identity_id（TikTok 广告必填）"}

    video_id = payload.get("video_id")
    if not video_id:
        return {"error": "缺少 video_id（请先在 TikTok 素材库上传视频）"}

    ad_text = payload.get("ad_text") or ""
    landing_url = payload.get("landing_url") or ""  # minis path / destination

    client = TikTokClient()
    results: dict = {
        "platform": "tiktok",
        "template_type": "tiktok_minis_basic",
        "campaign": None,
        "adgroup": None,
        "ad": None,
        "summary": {"total": 1, "success": 0, "fail": 0},
        "delivery_language": {
            "selected": selected_lang,
            "allowed": list(payload.get("_delivery_language_allowed") or []),
            "applied_tiktok_languages": list(languages),
        },
    }

    # ── Step 1: Campaign ──
    # 注意：本接口依赖 TikTok 给 advertiser 开通 Smart+ Campaign OpenAPI 写权限。
    # 未开通时 campaign/create/ 必报 [40002] Enter a valid Campaign Type，
    # 这是业务能力问题，不是字段问题（字段已与源 campaign 1863044185193761 完全对齐）。
    campaign_payload = {
        "advertiser_id": advertiser_id,
        "campaign_name": campaign_name,
        "objective_type": tpl_campaign.get("objective_type", "APP_PROMOTION"),
        "campaign_type": tpl_campaign.get("campaign_type", "REGULAR_CAMPAIGN"),
        "campaign_automation_type": tpl_campaign.get(
            "campaign_automation_type", "UPGRADED_SMART_PLUS"
        ),
        "budget_mode": tpl_campaign.get("budget_mode", "BUDGET_MODE_DYNAMIC_DAILY_BUDGET"),
        "operation_status": tpl_campaign.get("operation_status", "ENABLE"),
    }
    try:
        camp_data = await client.post("campaign/create/", campaign_payload)
        campaign_id = camp_data.get("campaign_id") or (camp_data.get("campaign_ids") or [""])[0]
        results["campaign"] = {"success": True, "campaign_id": campaign_id}
        logger.info(f"[launch-minis] Campaign 创建成功: {campaign_id}")
    except Exception as e:
        logger.error(f"[launch-minis] Campaign 创建失败: {e}  payload={campaign_payload}")
        # 把"能力未开通"识别成更友好的提示，避免反复纠结字段
        err_str = str(e)
        friendly_hint = ""
        if "Enter a valid Campaign Type" in err_str:
            friendly_hint = (
                "该广告主未开通 Smart+ Campaign OpenAPI 写权限，请联系 TikTok BC "
                f"为 advertiser_id={advertiser_id} 申请「Smart+ Campaign API write」能力。"
            )
        elif "dynamic daily budget is not supported" in err_str:
            friendly_hint = (
                "该广告主已识别但 Smart+ 能力未完全开通（DYNAMIC_DAILY_BUDGET 被业务侧拒），"
                f"请联系 TikTok BC 检查 advertiser_id={advertiser_id} 的 Smart+ OpenAPI 配置。"
            )
        results["campaign"] = {
            "success": False,
            "error": err_str,
            "hint": friendly_hint,
            "payload_sent": campaign_payload,
        }
        # campaign 失败时，下游两步不会执行 —— 给前端一个明确的 skipped 状态，
        # 避免 UI 渲染成 undefined。
        results["adgroup"] = {
            "success": False,
            "skipped": True,
            "reason": "未执行（因 Campaign 创建失败）",
        }
        results["ad"] = {
            "success": False,
            "skipped": True,
            "reason": "未执行（因 Campaign 创建失败）",
        }
        results["summary"]["fail"] = 1
        return {"data": results}

    # ── Step 2: Ad Group ──
    adgroup_payload: dict = {
        "advertiser_id": advertiser_id,
        "campaign_id": campaign_id,
        "adgroup_name": adgroup_name,
        "promotion_type": tpl_adgroup.get("promotion_type", "MINI_APP"),
        "placement_type": tpl_adgroup.get("placement_type", "PLACEMENT_TYPE_NORMAL"),
        "placements": tpl_adgroup.get("placements", ["PLACEMENT_TIKTOK"]),
        "billing_event": tpl_adgroup.get("billing_event", "OCPM"),
        "bid_type": tpl_adgroup.get("bid_type", "BID_TYPE_NO_BID"),
        "optimization_goal": tpl_adgroup.get("optimization_goal", "VALUE"),
        "optimization_event": tpl_adgroup.get("optimization_event", "ACTIVE_PAY"),
        "secondary_optimization_event": tpl_adgroup.get(
            "secondary_optimization_event", "PURCHASE_ROI"
        ),
        "deep_bid_type": tpl_adgroup.get("deep_bid_type", "VO_MIN_ROAS"),
        "vbo_window": tpl_adgroup.get("vbo_window", "ZERO_DAY"),
        "schedule_type": schedule_type,
        "budget_mode": tpl_adgroup.get("budget_mode", "BUDGET_MODE_DAY"),
        "budget": budget,
        "roas_bid": roas_bid,
        "app_id": app_id,
        "minis_id": minis_id,
        "location_ids": location_ids,
        "languages": languages,
        "gender": gender,
        "operation_status": tpl_adgroup.get("operation_status", "ENABLE"),
        "skip_learning_phase": tpl_adgroup.get("skip_learning_phase", True),
        "pacing": tpl_adgroup.get("pacing", "PACING_MODE_SMOOTH"),
    }
    if age_groups:
        adgroup_payload["age_groups"] = age_groups
    if schedule_start_time:
        adgroup_payload["schedule_start_time"] = schedule_start_time
    if schedule_end_time:
        adgroup_payload["schedule_end_time"] = schedule_end_time

    try:
        ag_data = await client.post("adgroup/create/", adgroup_payload)
        adgroup_id = ag_data.get("adgroup_id") or (ag_data.get("adgroup_ids") or [""])[0]
        results["adgroup"] = {"success": True, "adgroup_id": adgroup_id}
        logger.info(f"[launch-minis] AdGroup 创建成功: {adgroup_id}")
    except Exception as e:
        logger.error(f"[launch-minis] AdGroup 创建失败: {e}  payload={adgroup_payload}")
        results["adgroup"] = {"success": False, "error": str(e), "payload_sent": adgroup_payload}
        results["summary"]["fail"] = 1
        return {"data": results}

    # ── Step 3: Ad ──
    ad_payload: dict = {
        "advertiser_id": advertiser_id,
        "adgroup_id": adgroup_id,
        "ad_name": ad_name,
        "ad_text": ad_text,
        "ad_format": tpl_ad.get("ad_format", "SINGLE_VIDEO"),
        "video_id": video_id,
        "identity_id": identity_id,
        "identity_type": identity_type,
    }
    if landing_url:
        ad_payload["landing_page_url"] = landing_url

    try:
        ad_data = await client.post("ad/create/", ad_payload)
        ad_id = ad_data.get("ad_id") or (ad_data.get("ad_ids") or [""])[0]
        results["ad"] = {"success": True, "ad_id": ad_id, "ad_name": ad_name}
        results["summary"]["success"] = 1
        logger.info(f"[launch-minis] Ad 创建成功: {ad_id}")
    except Exception as e:
        logger.error(f"[launch-minis] Ad 创建失败: {e}  payload={ad_payload}")
        results["ad"] = {"success": False, "error": str(e), "payload_sent": ad_payload}
        results["summary"]["fail"] = 1

    return {"data": results}


# ══════════════════════════════════════════════════════════
#  TikTok Web to App 系统母版投放（最小可用版本）
#  · 单 campaign / 单 adgroup / 单 ad
#  · 只允许 editable_fields 白名单字段从 payload 覆盖 defaults
#  · 与 _launch_tiktok_minis 保持相同的错误展示风格（skipped + hint）
# ══════════════════════════════════════════════════════════

TIKTOK_W2A_EDITABLE_FIELDS: set[str] = {
    "campaign_name", "adgroup_name", "ad_name",
    "budget", "bid", "bid_price",
    "country", "countries", "location_ids",
    "age_groups", "gender", "audience", "languages",
    "landing_page_url", "tracking_params", "tracking_url", "deeplink",
    "video_id", "creative_id", "image_ids",
    "ad_text", "ad_title", "call_to_action",
    "schedule", "schedule_type", "schedule_start_time", "schedule_end_time",
    "identity_id", "identity_type",
    "pixel_id", "optimization_event",
    # 资产库引用 + 快照（不参与 TikTok 主调用，仅用于日志/operation_log/模板回填）
    "region_mode", "region_group", "region_group_id", "region_group_name_snapshot",
    "landing_page_id", "landing_page_name_snapshot", "landing_page_url_snapshot",
    "copy_pack_id", "copy_pack_name_snapshot",
}


async def _launch_tiktok_web_to_app(tpl: dict, payload: dict) -> dict:
    tpl_campaign = dict(tpl.get("campaign", {}))
    tpl_adgroup = dict(tpl.get("adgroup", {}))
    tpl_ad = dict(tpl.get("ad", {}))
    tpl_defaults = dict(tpl.get("defaults", {}))
    tpl_targeting = dict(tpl_defaults.get("targeting", {}))
    tpl_identity = dict(tpl_defaults.get("identity", {}))
    tpl_tracking = dict(tpl_defaults.get("tracking", {}))

    # ── 白名单覆盖 ──
    overrides = {k: v for k, v in payload.items() if k in TIKTOK_W2A_EDITABLE_FIELDS}

    advertiser_id = payload.get("advertiser_id", "").strip()
    if not advertiser_id:
        return {"error": "缺少 advertiser_id（TikTok 广告账户必填）"}

    # ── 为该 advertiser 找 access_token（阶段 2：走统一凭证服务） ──
    from services.credential_service import resolve_access_token
    access_token = resolve_access_token("tiktok", account_id=advertiser_id)
    if not access_token:
        return {"error": f"未找到 advertiser_id={advertiser_id} 对应的 TikTok access_token，请先完成 OAuth 授权"}

    campaign_name = (overrides.get("campaign_name") or payload.get("campaign_name") or "").strip()
    if not campaign_name:
        return {"error": "campaign_name 不能为空"}

    # 需求 1：AdGroup Name 留空时自动继承 Campaign Name
    adgroup_name = (overrides.get("adgroup_name") or "").strip() or campaign_name
    if not adgroup_name:
        adgroup_name = "AdGroup_01"

    # 需求 2：Ad Name 兜底优先级 = 用户输入 > 素材文件名(去后缀) > 默认 "{campaign_name}_Ad_01"
    # material_name 由前端在 payload 中透传（不进 EDITABLE_FIELDS，仅作 ad_name 兜底）
    raw_material_name = (payload.get("material_name") or "").strip()
    # 如果是带后缀的文件名，去掉扩展名
    if raw_material_name and "." in raw_material_name:
        dot = raw_material_name.rfind(".")
        if 0 < dot < len(raw_material_name) - 1:
            raw_material_name = raw_material_name[:dot]
    ad_name = (overrides.get("ad_name") or "").strip() or raw_material_name or f"{campaign_name}_Ad_01"

    budget = float(overrides.get("budget", tpl_adgroup.get("default_budget", 50)))
    bid_price = overrides.get("bid") or overrides.get("bid_price")

    # targeting
    location_ids = (
        overrides.get("location_ids")
        or tpl_targeting.get("location_ids")
        or []
    )
    if not location_ids:
        return {"error": "至少选择 1 个投放地区（location_ids 或 country / region_group）"}
    # 投放语种（强制开启）：忽略 overrides/template 里的 languages，统一使用 selected_delivery_language 的映射
    selected_lang = payload.get("selected_delivery_language") or DEFAULT_DELIVERY_LANGUAGE
    try:
        languages = resolve_tiktok_languages(selected_lang)
    except DeliveryLanguageError as e:
        return {"error": str(e)}
    age_groups = overrides.get("age_groups") or tpl_targeting.get("age_groups") or []
    gender = overrides.get("gender") or tpl_targeting.get("gender") or "GENDER_UNLIMITED"

    # schedule
    schedule_type = overrides.get("schedule_type") or tpl_adgroup.get(
        "schedule_type", "SCHEDULE_FROM_NOW"
    )
    schedule_start_time = overrides.get("schedule_start_time")
    schedule_end_time = overrides.get("schedule_end_time")

    # identity
    identity_id = overrides.get("identity_id")
    identity_type = overrides.get("identity_type") or tpl_identity.get(
        "identity_type", "CUSTOMIZED_USER"
    )
    if not identity_id:
        return {"error": "缺少 identity_id（TikTok 广告必填）"}

    # creative
    video_id = overrides.get("video_id")
    has_batch_materials = isinstance(payload.get("materials"), list) and bool(payload.get("materials"))
    if not video_id and not has_batch_materials:
        return {"error": "缺少 video_id（请先上传 TikTok 视频素材，或通过 materials 批量字段传入）"}

    # landing & tracking
    landing_url = overrides.get("landing_page_url") or ""
    if not landing_url:
        return {"error": "缺少 landing_page_url（Web to App 必填）"}
    tracking_url = overrides.get("tracking_url") or overrides.get("tracking_params") or ""

    # pixel (用于 WEB_CONVERSIONS objective 的 promoted_object)
    pixel_id = overrides.get("pixel_id") or tpl_tracking.get("pixel_id") or ""
    optimization_event = (
        overrides.get("optimization_event")
        or tpl_tracking.get("optimization_event")
        or tpl_adgroup.get("optimization_event")
        or "SHOPPING"
    )

    ad_text = overrides.get("ad_text") or ""
    call_to_action = overrides.get("call_to_action") or tpl_ad.get(
        "call_to_action", "LEARN_MORE"
    )

    # ── 资产库引用日志（不影响 TikTok 主调用，仅用于排查与可观测） ──
    asset_refs = {
        "region_mode": overrides.get("region_mode"),
        "region_group_id": overrides.get("region_group_id"),
        "region_group_name": overrides.get("region_group_name_snapshot"),
        "landing_page_id": overrides.get("landing_page_id"),
        "landing_page_name": overrides.get("landing_page_name_snapshot"),
        "copy_pack_id": overrides.get("copy_pack_id"),
        "copy_pack_name": overrides.get("copy_pack_name_snapshot"),
    }
    if any(v for v in asset_refs.values() if v not in (None, "")):
        logger.info(f"[launch-w2a] 使用资产库引用: { {k: v for k, v in asset_refs.items() if v not in (None, '')} }")

    client = TikTokClient(access_token=access_token)
    results: dict = {
        "platform": "tiktok",
        "template_type": "tiktok_web_to_app",
        "campaign": None,
        "adgroup": None,
        "ad": None,
        "summary": {"total": 1, "success": 0, "fail": 0},
        # 把资产库引用回带给前端，便于结果面板展示
        "asset_refs": {k: v for k, v in asset_refs.items() if v not in (None, "")},
        "delivery_language": {
            "selected": selected_lang,
            "allowed": list(payload.get("_delivery_language_allowed") or []),
            "applied_tiktok_languages": list(languages),
        },
    }

    # ── Step 1: Campaign ──
    campaign_payload = {
        "advertiser_id": advertiser_id,
        "campaign_name": campaign_name,
        "objective_type": tpl_campaign.get("objective_type", "WEB_CONVERSIONS"),
        "campaign_type": tpl_campaign.get("campaign_type", "REGULAR_CAMPAIGN"),
        "budget_mode": tpl_campaign.get("budget_mode", "BUDGET_MODE_INFINITE"),
        "operation_status": tpl_campaign.get("operation_status", "ENABLE"),
    }
    try:
        camp_data = await client.post("campaign/create/", campaign_payload)
        campaign_id = camp_data.get("campaign_id") or (camp_data.get("campaign_ids") or [""])[0]
        results["campaign"] = {"success": True, "campaign_id": campaign_id}
        logger.info(f"[launch-w2a] Campaign 创建成功: {campaign_id}")
    except Exception as e:
        logger.error(f"[launch-w2a] Campaign 创建失败: {e}  payload={campaign_payload}")
        results["campaign"] = {"success": False, "error": str(e), "payload_sent": campaign_payload}
        results["adgroup"] = {"success": False, "skipped": True, "reason": "未执行（因 Campaign 创建失败）"}
        results["ad"] = {"success": False, "skipped": True, "reason": "未执行（因 Campaign 创建失败）"}
        results["summary"]["fail"] = 1
        return {"data": results}

    # ── Step 2: Ad Group ──
    adgroup_payload: dict = {
        "advertiser_id": advertiser_id,
        "campaign_id": campaign_id,
        "adgroup_name": adgroup_name,
        "promotion_type": tpl_adgroup.get("promotion_type", "WEBSITE"),
        "placement_type": tpl_adgroup.get("placement_type", "PLACEMENT_TYPE_AUTOMATIC"),
        "billing_event": tpl_adgroup.get("billing_event", "OCPM"),
        "bid_type": tpl_adgroup.get("bid_type", "BID_TYPE_NO_BID"),
        "optimization_goal": tpl_adgroup.get("optimization_goal", "CONVERT"),
        "schedule_type": schedule_type,
        "budget_mode": tpl_adgroup.get("budget_mode", "BUDGET_MODE_DAY"),
        "budget": budget,
        "location_ids": location_ids,
        "languages": languages,
        "gender": gender,
        "operation_status": tpl_adgroup.get("operation_status", "ENABLE"),
        "pacing": tpl_adgroup.get("pacing", "PACING_MODE_SMOOTH"),
        "landing_page_url": landing_url,
    }
    if age_groups:
        adgroup_payload["age_groups"] = age_groups
    if tpl_adgroup.get("placement_type") == "PLACEMENT_TYPE_NORMAL" and tpl_adgroup.get("placements"):
        adgroup_payload["placements"] = tpl_adgroup["placements"]
    if schedule_start_time:
        adgroup_payload["schedule_start_time"] = schedule_start_time
    if schedule_end_time:
        adgroup_payload["schedule_end_time"] = schedule_end_time
    if pixel_id and optimization_event:
        adgroup_payload["pixel_id"] = pixel_id
        adgroup_payload["optimization_event"] = optimization_event
    if bid_price:
        adgroup_payload["bid_price"] = float(bid_price)
        adgroup_payload["bid_type"] = "BID_TYPE_CUSTOM"

    try:
        ag_data = await client.post("adgroup/create/", adgroup_payload)
        adgroup_id = ag_data.get("adgroup_id") or (ag_data.get("adgroup_ids") or [""])[0]
        results["adgroup"] = {"success": True, "adgroup_id": adgroup_id}
        logger.info(f"[launch-w2a] AdGroup 创建成功: {adgroup_id}")
    except Exception as e:
        logger.error(f"[launch-w2a] AdGroup 创建失败: {e}  payload={adgroup_payload}")
        results["adgroup"] = {"success": False, "error": str(e), "payload_sent": adgroup_payload}
        results["ad"] = {"success": False, "skipped": True, "reason": "未执行（因 AdGroup 创建失败）"}
        results["summary"]["fail"] = 1
        return {"data": results}

    # ── Step 3: Ad（支持批量素材：1 campaign + 1 adgroup + N ad）──
    # TikTok v1.3 ad/create/ 在 WEB_CONVERSIONS + SINGLE_VIDEO 组合下，
    # 强制要求把素材维度字段放进 creatives 数组里，顶层只保留 advertiser_id / adgroup_id。
    # 本模板永远走 SINGLE_VIDEO，不允许被改成 IMAGE / CAROUSEL。
    ad_format = "SINGLE_VIDEO"
    deeplink = overrides.get("deeplink")

    # ── 构造素材列表 ──
    #   优先使用 payload.materials（批量模式：每条对应一个 ad）；
    #   未提供时回落到顶层 video_id（兼容旧前端单素材模式）。
    raw_materials = payload.get("materials")
    materials_list: list[dict] = []
    if isinstance(raw_materials, list) and raw_materials:
        for item in raw_materials:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("video_id") or "").strip()
            if not vid:
                continue
            materials_list.append({
                "video_id": vid,
                "ad_name": str(item.get("ad_name") or "").strip(),
                "image_ids_raw": item.get("image_ids"),
                "file_name": str(item.get("file_name") or item.get("material_name") or "").strip(),
            })
    if not materials_list:
        # 旧路径兼容：单素材
        materials_list.append({
            "video_id": video_id,
            "ad_name": ad_name,
            "image_ids_raw": overrides.get("image_ids"),
            "file_name": "",
        })

    # ── ad_name 兜底 + 重名加序号 ──
    seen_names: dict[str, int] = {}
    for m in materials_list:
        base = m["ad_name"] or m["file_name"] or f"{campaign_name}_Ad"
        if "." in base:
            dot = base.rfind(".")
            if 0 < dot < len(base) - 1:
                base = base[:dot]
        n = seen_names.get(base, 0) + 1
        seen_names[base] = n
        # 第一次保留原名；第 2+ 次追加序号
        m["ad_name"] = base if n == 1 else f"{base}_{n:02d}"

    # ── 总数与结果壳更新 ──
    total_ads = len(materials_list)
    results["summary"]["total"] = total_ads
    results["ads"] = []  # 批量模式主结果
    # 兼容旧前端：单条时同步给 results.ad
    results["ad"] = None

    creative_svc = None  # 懒加载

    async def _resolve_image_ids_for(vid: str, raw: object) -> tuple[list[str], str]:
        """返回 (image_ids, note)；note 用于错误展示"""
        # 1) 优先用 payload 透传值
        if isinstance(raw, str):
            ids = [s.strip() for s in raw.split(",") if s.strip()]
        elif isinstance(raw, list):
            ids = [str(x).strip() for x in raw if str(x).strip()]
        else:
            ids = []
        if ids:
            return ids, ""
        # 2) 自动从视频封面生成
        nonlocal creative_svc
        if creative_svc is None:
            from tiktok_ads.api.creative import CreativeService
            creative_svc = CreativeService(client=client, advertiser_id=advertiser_id)
        try:
            video_infos = await creative_svc.get_video_info_detail([vid])
            cover_url = ""
            if video_infos:
                v0 = video_infos[0] or {}
                cover_url = (
                    v0.get("video_cover_url")
                    or v0.get("poster_url")
                    or v0.get("preview_url")
                    or ""
                )
            if not cover_url:
                return [], "TikTok 未在 video info 中返回封面 URL"
            cover_resp = await creative_svc.upload_image_by_url(
                image_url=cover_url,
                file_name=f"cover_{str(vid)[:16]}.jpg",
            )
            cov_id = (
                cover_resp.get("image_id")
                or (cover_resp.get("data") or {}).get("image_id")
            )
            if cov_id:
                logger.info(f"[launch-w2a] 自动生成封面 image_id={cov_id} (video={vid})")
                return [cov_id], f"已自动生成封面 image_id={cov_id}"
            return [], f"上传封面接口未返回 image_id，响应: {cover_resp}"
        except Exception as e:
            logger.warning(f"[launch-w2a] 自动生成视频封面失败 (video={vid}): {e}")
            return [], f"自动生成封面失败: {e}"

    # ── 循环创建每条 Ad ──
    for idx, m in enumerate(materials_list, start=1):
        vid = m["video_id"]
        an = m["ad_name"]
        image_ids, cover_note = await _resolve_image_ids_for(vid, m["image_ids_raw"])

        if not image_ids:
            err = (
                "缺少视频封面图 image_ids。该模板强制为 SINGLE_VIDEO，TikTok 要求必须传 cover image_id。"
                f" {cover_note}。请在前端「素材」页为该视频准备封面后重试，或在请求中显式传 image_ids。"
            )
            logger.error(f"[launch-w2a] Ad #{idx} 拦截: {err}")
            results["ads"].append({
                "success": False,
                "error": err,
                "video_id": vid,
                "ad_name": an,
                "skipped_call": True,
            })
            results["summary"]["fail"] += 1
            continue

        creative_item: dict = {
            "ad_name": an,
            "ad_text": ad_text,
            "ad_format": ad_format,
            "video_id": vid,
            "image_ids": image_ids,
            "identity_id": identity_id,
            "identity_type": identity_type,
            "call_to_action": call_to_action,
            "landing_page_url": landing_url,
        }
        if tracking_url:
            creative_item["tracking_url"] = tracking_url
        if deeplink:
            creative_item["deeplink"] = deeplink
        # ad_title 历史上被错误地映射成 display_name(那是 identity 的字段)。
        # v1.3 creatives 没有 display_name；本次先不下发。

        ad_payload: dict = {
            "advertiser_id": advertiser_id,
            "adgroup_id": adgroup_id,
            "creatives": [creative_item],
        }

        try:
            ad_data = await client.post("ad/create/", ad_payload)
            ad_id = (
                ad_data.get("ad_id")
                or (ad_data.get("ad_ids") or [""])[0]
                or ((ad_data.get("creatives") or [{}])[0].get("ad_id"))
            )
            results["ads"].append({
                "success": True,
                "ad_id": ad_id,
                "ad_name": an,
                "video_id": vid,
            })
            results["summary"]["success"] += 1
            logger.info(f"[launch-w2a] Ad #{idx}/{total_ads} 创建成功: {ad_id} (name={an})")
        except Exception as e:
            logger.error(f"[launch-w2a] Ad #{idx}/{total_ads} 创建失败: {e}  payload={ad_payload}")
            results["ads"].append({
                "success": False,
                "error": str(e),
                "video_id": vid,
                "ad_name": an,
                "payload_sent": ad_payload,
            })
            results["summary"]["fail"] += 1

    # 单条兼容 alias
    if results["ads"]:
        results["ad"] = results["ads"][0]

    return {"data": results}


# ══════════════════════════════════════════════════════════
#  源广告链探测（用于 TikTok Web to App 系统母版 defaults 固化）
#  GET /api/templates/system/tiktok-w2a/probe
#    ?advertiser_id=&campaign_id=&adgroup_id=&ad_id=
#  返回抽取后的 defaults JSON；运维将结果回填到 BUILTIN_TEMPLATES 后重启即可
# ══════════════════════════════════════════════════════════

# 运行态字段黑名单（不会被写进 defaults）
TIKTOK_W2A_RUNTIME_KEYS: set[str] = {
    # IDs
    "campaign_id", "adgroup_id", "ad_id",
    "creative_material_mode", "creative_material_id",
    # 时间戳
    "create_time", "modify_time", "expires_at", "launch_time",
    # 实时状态/审核
    "status", "secondary_status", "operation_status_running",
    "approval_status", "approved_status", "review_status", "audit_status",
    "review_message", "rejection_reason", "approved_ad_accounts",
    "is_new_structure",
    # 报表/表现
    "spend", "impressions", "clicks", "conversions", "cpa", "cpc", "cpm",
    "ctr", "cvr", "reach", "result_rate", "budget_remaining",
    # URL 资源（每次投放都是新的）
    "video_cover_url", "video_preview_url", "image_url",
    "material_url", "thumbnail_url", "image_web_uri",
    # 学习态
    "learning_phase", "is_learning_phase",
}


def _clean_runtime(d: dict) -> dict:
    """深度过滤 TikTok API 返回结构中的运行态字段。"""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if k in TIKTOK_W2A_RUNTIME_KEYS:
            continue
        if isinstance(v, dict):
            out[k] = _clean_runtime(v)
        elif isinstance(v, list):
            out[k] = [
                _clean_runtime(x) if isinstance(x, dict) else x
                for x in v
                if not (isinstance(x, dict) and all(k2 in TIKTOK_W2A_RUNTIME_KEYS for k2 in x))
            ]
        else:
            out[k] = v
    return out


@router.get("/system/tiktok-w2a/probe")
async def probe_tiktok_w2a_source(
    advertiser_id: str = Query(..., description="TikTok advertiser_id"),
    campaign_id: str = Query(..., description="源 campaign_id"),
    adgroup_id: str = Query(..., description="源 adgroup_id"),
    ad_id: str = Query(..., description="源 ad_id"),
    _user: User = Depends(get_current_user),
):
    """从源广告链抽取可复用 defaults，供运维回填 BUILTIN_TEMPLATES。

    返回结构：
      source_ids: {...}
      defaults:  抽取后的模板默认值（可直接贴回 tpl_tiktok_web_to_app_system.defaults）
      raw:       campaign/adgroup/ad 原始返回（已过滤运行态），便于人工核对
    """
    from services.credential_service import resolve_access_token
    _token = resolve_access_token("tiktok", account_id=advertiser_id)
    if not _token:
        return {"error": f"未找到 advertiser_id={advertiser_id} 对应的 TikTok access_token"}
    client = TikTokClient(access_token=_token, account_id=advertiser_id)

    try:
        campaign_resp = await client.get("campaign/get/", {
            "advertiser_id": advertiser_id,
            "filtering": json.dumps({"campaign_ids": [campaign_id]}),
            "page_size": 1,
        })
        adgroup_resp = await client.get("adgroup/get/", {
            "advertiser_id": advertiser_id,
            "filtering": json.dumps({"campaign_ids": [campaign_id], "adgroup_ids": [adgroup_id]}),
            "page_size": 1,
        })
        ad_resp = await client.get("ad/get/", {
            "advertiser_id": advertiser_id,
            "filtering": json.dumps({"adgroup_ids": [adgroup_id], "ad_ids": [ad_id]}),
            "page_size": 1,
        })
    except Exception as e:
        logger.error(f"[probe-w2a] TikTok API 调用失败: {e}")
        return {"error": f"TikTok API 调用失败: {e}"}

    campaign = (campaign_resp.get("list") or [{}])[0] if isinstance(campaign_resp, dict) else {}
    adgroup = (adgroup_resp.get("list") or [{}])[0] if isinstance(adgroup_resp, dict) else {}
    ad = (ad_resp.get("list") or [{}])[0] if isinstance(ad_resp, dict) else {}

    campaign_clean = _clean_runtime(campaign)
    adgroup_clean = _clean_runtime(adgroup)
    ad_clean = _clean_runtime(ad)

    # 抽取可复用 defaults
    defaults = {
        "objective_type": campaign_clean.get("objective_type"),
        "campaign_budget_mode": campaign_clean.get("budget_mode"),
        "campaign_status": campaign_clean.get("operation_status"),
        "adgroup_budget_mode": adgroup_clean.get("budget_mode"),
        "billing_event": adgroup_clean.get("billing_event"),
        "optimization_goal": adgroup_clean.get("optimization_goal"),
        "bid_type": adgroup_clean.get("bid_type"),
        "pacing": adgroup_clean.get("pacing"),
        "schedule_type": adgroup_clean.get("schedule_type"),
        "operating_system": adgroup_clean.get("operating_systems") or [],
        "placement": {
            "placement_type": adgroup_clean.get("placement_type"),
            "placements": adgroup_clean.get("placements") or [],
        },
        "targeting": {
            "age_groups": adgroup_clean.get("age_groups") or [],
            "gender": adgroup_clean.get("gender"),
            "languages": adgroup_clean.get("languages") or [],
            "location_ids": adgroup_clean.get("location_ids") or [],
        },
        "identity": {
            "identity_type": ad_clean.get("identity_type"),
        },
        "tracking": {
            "pixel_id": adgroup_clean.get("pixel_id"),
            "optimization_event": adgroup_clean.get("optimization_event")
                or adgroup_clean.get("event"),
            "tracking_url": ad_clean.get("tracking_url"),
        },
        "creative_format": ad_clean.get("ad_format"),
        "call_to_action": ad_clean.get("call_to_action"),
        "landing_page_template": ad_clean.get("landing_page_url"),
    }

    return {
        "data": {
            "source_ids": {
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id,
                "adgroup_id": adgroup_id,
                "ad_id": ad_id,
            },
            "defaults": defaults,
            "raw": {
                "campaign": campaign_clean,
                "adgroup": adgroup_clean,
                "ad": ad_clean,
            },
        }
    }


def _age_groups_from_min(age_min: int) -> list[str]:
    """根据最低年龄生成 TikTok age_groups 列表"""
    all_groups = [
        ("AGE_13_17", 13), ("AGE_18_24", 18), ("AGE_25_34", 25),
        ("AGE_35_44", 35), ("AGE_45_54", 45), ("AGE_55_100", 55),
    ]
    return [g for g, a in all_groups if a >= age_min]


# ── 日志辅助函数 ──────────────────────────────────────────

_SENSITIVE_KEYS = {"access_token", "app_secret", "password", "cookie", "secret"}


def _tpl_summary(tpl: dict | None) -> dict | None:
    """提取模板摘要用于日志存储，排除敏感字段和超大内容。"""
    if not tpl:
        return None
    summary: dict = {}
    for k, v in tpl.items():
        if k in _SENSITIVE_KEYS:
            continue
        if isinstance(v, dict):
            summary[k] = {ik: iv for ik, iv in v.items() if ik not in _SENSITIVE_KEYS}
        elif isinstance(v, str) and len(v) > 500:
            summary[k] = v[:500] + "..."
        else:
            summary[k] = v
    return summary


def _diff_fields(old: dict, new: dict, prefix: str = "") -> list[str]:
    """对比两个字典，返回变更字段列表（支持一层嵌套）。"""
    changed: list[str] = []
    all_keys = set(old.keys()) | set(new.keys())
    skip = {"updated_at", "created_at"}
    for k in sorted(all_keys):
        if k in skip:
            continue
        full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        ov, nv = old.get(k), new.get(k)
        if isinstance(ov, dict) and isinstance(nv, dict):
            changed.extend(_diff_fields(ov, nv, full_key))
        elif ov != nv:
            changed.append(full_key)
    return changed


def _log_launch(user, tpl_id: str, platform: str, payload: dict, resp: dict):
    """记录模板投放操作日志（兼容新批量结构与旧单 ad 结构）。"""
    data = resp.get("data", {})
    error = resp.get("error")
    template_type = data.get("template_type", "") if isinstance(data, dict) else ""

    campaign_name = payload.get("campaign_name", "")
    ad_account_id = payload.get("ad_account_id", "")

    materials = payload.get("materials", [])
    adsets_input = payload.get("adsets", [])

    if error:
        status = "fail"
        detail = f"template={tpl_id} | platform={platform} | error: {error}"
    elif isinstance(data.get("adsets"), list):
        # 新批量结构
        camp = data.get("campaign", {})
        camp_ok = camp.get("success", False)
        adsets_results = data.get("adsets", [])
        total_ads = sum(len(a.get("ads", [])) for a in adsets_results)
        ok_adsets = sum(1 for a in adsets_results if a.get("success"))
        ok_ads = sum(1 for a in adsets_results for ad in a.get("ads", []) if ad.get("success"))

        if not camp_ok:
            status = "fail"
            _err = (camp.get("error") or "").strip()
            _meta_msg = (camp.get("meta_error_message") or "").strip()
            _meta_code = camp.get("meta_error_code")
            _meta_sub = camp.get("meta_error_subcode")
            if not _err:
                _err = _meta_msg or "unknown"
            _suffix = ""
            if _meta_code or _meta_sub:
                _suffix = f" [code={_meta_code or '?'} subcode={_meta_sub or '?'}]"
            detail = f"template={tpl_id} | campaign创建失败: {_err}{_suffix}"
        elif ok_adsets == 0:
            status = "fail"
            detail = f"template={tpl_id} | 所有adset创建失败 ({len(adsets_results)} 个)"
        elif ok_adsets < len(adsets_results) or ok_ads < total_ads:
            status = "partial"
            detail = (f"template={tpl_id} | campaign={camp.get('campaign_id', '')} | "
                      f"adsets: {ok_adsets}/{len(adsets_results)} | ads: {ok_ads}/{total_ads}")
        else:
            status = "success"
            detail = (f"template={tpl_id} | campaign={camp.get('campaign_id', '')} | "
                      f"adsets: {ok_adsets} | ads: {ok_ads}")
    else:
        # 旧单 ad 结构（TikTok 等）
        failed_step = ""
        for step_name in ("campaign", "adset", "adgroup", "ad"):
            step_data = data.get(step_name)
            if isinstance(step_data, dict) and not step_data.get("success"):
                failed_step = step_name
                break
        if failed_step:
            step_err = data.get(failed_step, {}).get("error", "unknown")
            status = "fail"
            detail = f"template={tpl_id} | failed_step={failed_step} | error: {step_err}"
        else:
            status = "success"
            ids = []
            for k in ("campaign", "adset", "adgroup", "ad"):
                v = data.get(k, {})
                if isinstance(v, dict):
                    for id_key in ("campaign_id", "adset_id", "adgroup_id", "ad_id"):
                        if v.get(id_key):
                            ids.append(f"{k}={v[id_key]}")
            detail = f"template={tpl_id} | {', '.join(ids)}"

    if ad_account_id:
        detail += f" | account={ad_account_id}"

    after_summary: dict = {
        "template_id": tpl_id,
        "template_type": template_type,
        "platform": platform,
        "campaign_name": campaign_name,
        "materials_count": len(materials),
        "adsets_count": len(adsets_input),
    }
    if ad_account_id:
        after_summary["ad_account_id"] = ad_account_id

    # ── 投放语种：优先取 launch 已注入的 results.delivery_language，
    #    退化到 payload，缺失也写最少一份 selected/allowed 便于审计。
    dl_from_data = data.get("delivery_language") if isinstance(data, dict) else None
    selected_lang = (
        (dl_from_data or {}).get("selected")
        if isinstance(dl_from_data, dict) else None
    ) or payload.get("selected_delivery_language")
    allowed_langs = (
        (dl_from_data or {}).get("allowed")
        if isinstance(dl_from_data, dict) else None
    ) or payload.get("_delivery_language_allowed") or []
    if selected_lang or allowed_langs or isinstance(dl_from_data, dict):
        dl_record: dict = {
            "selected": selected_lang,
            "allowed": list(allowed_langs) if isinstance(allowed_langs, list) else [],
        }
        if isinstance(dl_from_data, dict):
            if dl_from_data.get("applied_meta_locales") is not None:
                dl_record["applied_meta_locales"] = dl_from_data["applied_meta_locales"]
            if dl_from_data.get("applied_tiktok_languages") is not None:
                dl_record["applied_tiktok_languages"] = dl_from_data["applied_tiktok_languages"]
        after_summary["delivery_language"] = dl_record

    # Meta W2A Conversion ABO 优化：记录素材来源分布 + 投放时间
    if platform == "meta" and isinstance(materials, list) and materials:
        local_cnt = sum(1 for m in materials if (m.get("source") == "local_upload"))
        account_cnt = sum(1 for m in materials if (m.get("source") == "account_asset"))
        after_summary["material_source"] = {
            "local_upload": local_cnt,
            "account_asset": account_cnt,
            "other": max(0, len(materials) - local_cnt - account_cnt),
        }
    # Meta 预算模式（CBO / ABO）+ 实际下发预算（cents）
    if platform == "meta" and isinstance(data, dict) and data.get("budget_mode"):
        after_summary["budget_mode"] = data.get("budget_mode")
        after_summary["campaign_daily_budget"] = data.get("campaign_daily_budget")
        after_summary["adset_daily_budget"] = data.get("adset_daily_budget")
    sched = data.get("schedule") if isinstance(data, dict) else None
    if isinstance(sched, dict) and sched.get("enabled"):
        after_summary["adset_schedule"] = {
            "enabled": True,
            "start_time": sched.get("start_time"),
            "end_time": sched.get("end_time"),
            "timezone": sched.get("timezone"),
        }
    # 失败素材 error 摘要（最多 5 个）
    if isinstance(data, dict) and isinstance(data.get("adsets"), list):
        failed_ads = []
        for a in data["adsets"]:
            for ad in a.get("ads", []):
                if not ad.get("success"):
                    failed_ads.append({
                        "ad_name": ad.get("ad_name"),
                        "material_name": ad.get("material_name"),
                        "error": ad.get("error", ""),
                    })
                if len(failed_ads) >= 5:
                    break
            if len(failed_ads) >= 5:
                break
        if failed_ads:
            after_summary["failed_ads"] = failed_ads

    log_operation(
        username=user.username,
        action="使用模板创建广告",
        target_type="template_launch",
        target_id=tpl_id,
        platform=platform,
        status=status,
        after_data=after_summary,
        error_message=detail,
    )
