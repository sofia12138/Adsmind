"""素材管理路由"""

from fastapi import APIRouter, Query
from loguru import logger

from tiktok_ads.api.creative import CreativeService
from tiktok_ads.api.client import TikTokClient
from repositories import biz_account_repository

router = APIRouter(prefix="/creatives", tags=["素材管理"])


@router.get("/videos")
async def list_videos(page: int = Query(1), page_size: int = Query(20)):
    service = CreativeService()
    return {"data": await service.list_videos(page, page_size)}


@router.get("/videos/info")
async def get_video_info(video_ids: str = Query(..., description="逗号分隔的视频ID")):
    service = CreativeService()
    ids = [v.strip() for v in video_ids.split(",")]
    return {"data": await service.get_video_info(ids)}


@router.get("/images")
async def list_images(page: int = Query(1), page_size: int = Query(20)):
    service = CreativeService()
    return {"data": await service.list_images(page, page_size)}


@router.get("/apps")
async def list_apps():
    service = CreativeService()
    return {"data": await service.list_apps()}


@router.get("/identities")
async def list_identities(
    advertiser_id: str | None = Query(None, description="广告主 ID，缺省则用配置默认值"),
    identity_type: str | None = Query(
        None,
        description="单个 identity_type；不传则合并 BC_AUTH_TT / TT_USER / CUSTOMIZED_USER 多类型",
    ),
):
    """聚合返回某广告主下的可用 Identity 列表。

    TikTok identity/get/ 一次只返回一种 identity_type，前端要做下拉合并体验，
    所以这里默认串行调用三种常见类型并去重合并；调用方也可显式只查一种。
    返回结构 {"data": {"identity_list": [...], "errors": [...]}}.
    """
    service = CreativeService(advertiser_id=advertiser_id)
    types = [identity_type] if identity_type else ["BC_AUTH_TT", "TT_USER", "CUSTOMIZED_USER"]

    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    errors: list[dict] = []
    for t in types:
        try:
            raw = await service.list_identities(t)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"identity/get/ 调用失败 type={t}: {exc}")
            errors.append({"identity_type": t, "error": str(exc)})
            continue
        # raw 可能是 {"identity_list": [...]} 或 {"list": [...]} —— 兼容两种
        if isinstance(raw, dict):
            items = raw.get("identity_list") or raw.get("list") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("identity_id") or it.get("id") or "").strip()
            itype = str(it.get("identity_type") or t).strip()
            if not iid:
                continue
            key = (iid, itype)
            if key in seen:
                continue
            seen.add(key)
            merged.append({
                "identity_id": iid,
                "identity_type": itype,
                "display_name": it.get("display_name") or it.get("identity_name") or iid,
                "profile_image": it.get("profile_image") or it.get("avatar_uri") or "",
            })
    return {"data": {"identity_list": merged, "errors": errors}}


# ══════════════════════════════════════════════════════════
#  TikTok Pixel + 优化事件
#  · GET /api/creatives/pixels?advertiser_id=...
#    一次返回该 advertiser 下所有 pixel + 嵌套事件列表
#    用于前端两级联动选择器（先选 pixel，再选 event）
#  · API 不稳定时返回 {"pixel_list": [], "errors": [...]}，
#    前端按"暂无可用 Pixel + 手动输入兜底"渲染，但仍然走下拉而非纯文本输入
# ══════════════════════════════════════════════════════════

# pixel/list 返回里 events 节点的字段名在 v1.3 不同账户/不同 pixel 模式下会有差异：
# 常见有：external_event_type / event_code / event_type / event_name / name / display_name
# 这里做宽松抽取，统一映射到前端：{event_code, event_name, event_type}
def _normalize_pixel_events(raw_events) -> list[dict]:
    if not isinstance(raw_events, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        code = (
            ev.get("external_event_type")
            or ev.get("event_code")
            or ev.get("event_type")
            or ev.get("code")
            or ""
        )
        code = str(code).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        name = (
            ev.get("event_name")
            or ev.get("name")
            or ev.get("display_name")
            or code
        )
        out.append({
            "event_code": code,
            "event_name": str(name),
            "event_type": ev.get("event_type") or "STANDARD",
        })
    return out


@router.get("/pixels")
async def list_pixels(
    advertiser_id: str = Query(..., description="TikTok advertiser_id"),
):
    """拉取 advertiser 下所有 pixel + 嵌套事件列表（用于前端两级联动）。

    返回结构：
      data.pixel_list: [{pixel_id, pixel_name, pixel_mode, events:[{event_code,event_name,event_type}]}]
      data.errors:     非空表示 API 调用失败，前端应展示"手动输入 Pixel ID"兜底
    """
    if not advertiser_id:
        return {"data": {"pixel_list": [], "errors": [{"error": "advertiser_id 不能为空"}]}}

    # 阶段 2：从统一凭证服务取 token（加密表 → 兼容路径），不再直接读 biz 明文
    from services.credential_service import resolve_access_token
    _token = resolve_access_token("tiktok", account_id=advertiser_id)
    acc_row = biz_account_repository.get_by_platform_account("tiktok", advertiser_id)
    if not _token:
        return {
            "data": {
                "pixel_list": [],
                "errors": [{"error": f"未找到 advertiser_id={advertiser_id} 对应的 access_token"}],
            }
        }

    client = TikTokClient(access_token=_token, account_id=advertiser_id)
    errors: list[dict] = []
    pixels: list[dict] = []

    # TikTok pixel/list/ 限制 page_size 最大 20，分页拉取直到拿完
    raw_list: list[dict] = []
    page = 1
    while True:
        try:
            resp = await client.get("pixel/list/", {
                "advertiser_id": advertiser_id,
                "page": page,
                "page_size": 20,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"pixel/list/ 调用失败 advertiser={advertiser_id} page={page}: {exc}")
            errors.append({"error": str(exc)})
            break

        if not isinstance(resp, dict):
            break

        page_items = (
            resp.get("pixels")
            or resp.get("list")
            or resp.get("pixel_list")
            or []
        )
        if not page_items:
            break
        raw_list.extend(page_items)

        # 翻页终止条件：拿到 page_info 时按 total_number 判断；拿不到时按本页 < page_size
        page_info = resp.get("page_info") or {}
        total = page_info.get("total_number") or page_info.get("total_count")
        if total is not None and len(raw_list) >= int(total):
            break
        if len(page_items) < 20:
            break
        page += 1
        if page > 10:  # 安全上限：最多 200 个 pixel
            break

    for p in raw_list or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("pixel_id") or p.get("id") or "").strip()
        if not pid:
            continue
        pixels.append({
            "pixel_id": pid,
            "pixel_name": p.get("pixel_name") or p.get("name") or pid,
            "pixel_mode": p.get("pixel_mode") or p.get("mode") or "",
            "pixel_category": p.get("pixel_category") or "",
            "events": _normalize_pixel_events(p.get("events") or p.get("event_list") or []),
        })

    return {"data": {"pixel_list": pixels, "errors": errors}}
