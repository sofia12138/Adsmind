"""广告资产库 — 推广链接 / 文案包 / 地区组 统一 API"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from auth import get_current_user, User
from services.oplog_service import log_operation
from repositories import (
    asset_landing_page_repository,
    asset_copy_pack_repository,
    asset_region_group_repository,
)

router = APIRouter(prefix="/ad-assets", tags=["广告资产库"])

# ═══════════════════════════════════════════════════════════
#  推广链接
# ═══════════════════════════════════════════════════════════

@router.get("/landing-pages")
async def list_landing_pages(
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    _user: User = Depends(get_current_user),
):
    rows = asset_landing_page_repository.list_all(status=status, keyword=keyword)
    return {"data": rows}


@router.get("/landing-pages/{asset_id}")
async def get_landing_page(asset_id: int, _user: User = Depends(get_current_user)):
    row = asset_landing_page_repository.get_by_id(asset_id)
    if not row:
        return {"error": "推广链接不存在"}
    return {"data": row}


@router.post("/landing-pages")
async def create_landing_page(body: dict = Body(...), user: User = Depends(get_current_user)):
    row = asset_landing_page_repository.create(
        name=body.get("name", ""),
        landing_page_url=body.get("landing_page_url", ""),
        product_name=body.get("product_name", ""),
        channel=body.get("channel", ""),
        language=body.get("language", ""),
        region_tags=body.get("region_tags"),
        remark=body.get("remark", ""),
        created_by=user.username,
        org_id=body.get("org_id", ""),
    )
    log_operation(username=user.username, action="创建推广链接资产",
                  target_type="asset_landing_page", target_id=str(row["id"]))
    return {"data": row}


@router.put("/landing-pages/{asset_id}")
async def update_landing_page(asset_id: int, body: dict = Body(...), user: User = Depends(get_current_user)):
    row = asset_landing_page_repository.update(asset_id, **body)
    if not row:
        return {"error": "推广链接不存在"}
    log_operation(username=user.username, action="更新推广链接资产",
                  target_type="asset_landing_page", target_id=str(asset_id))
    return {"data": row}


@router.delete("/landing-pages/{asset_id}")
async def delete_landing_page(asset_id: int, user: User = Depends(get_current_user)):
    ok = asset_landing_page_repository.delete(asset_id)
    if not ok:
        return {"error": "推广链接不存在"}
    log_operation(username=user.username, action="删除推广链接资产",
                  target_type="asset_landing_page", target_id=str(asset_id))
    return {"ok": True}


@router.post("/landing-pages/{asset_id}/toggle")
async def toggle_landing_page(asset_id: int, user: User = Depends(get_current_user)):
    row = asset_landing_page_repository.toggle_status(asset_id)
    if not row:
        return {"error": "推广链接不存在"}
    log_operation(username=user.username, action=f"{'启用' if row['status'] == 'active' else '停用'}推广链接资产",
                  target_type="asset_landing_page", target_id=str(asset_id))
    return {"data": row}


# ═══════════════════════════════════════════════════════════
#  文案包库
# ═══════════════════════════════════════════════════════════

@router.get("/copy-packs")
async def list_copy_packs(
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    _user: User = Depends(get_current_user),
):
    rows = asset_copy_pack_repository.list_all(status=status, keyword=keyword)
    return {"data": rows}


@router.get("/copy-packs/{asset_id}")
async def get_copy_pack(asset_id: int, _user: User = Depends(get_current_user)):
    row = asset_copy_pack_repository.get_by_id(asset_id)
    if not row:
        return {"error": "文案包不存在"}
    return {"data": row}


@router.post("/copy-packs")
async def create_copy_pack(body: dict = Body(...), user: User = Depends(get_current_user)):
    row = asset_copy_pack_repository.create(
        name=body.get("name", ""),
        primary_text=body.get("primary_text", ""),
        headline=body.get("headline", ""),
        description=body.get("description", ""),
        language=body.get("language", ""),
        product_name=body.get("product_name", ""),
        channel=body.get("channel", ""),
        country_tags=body.get("country_tags"),
        theme_tags=body.get("theme_tags"),
        remark=body.get("remark", ""),
        created_by=user.username,
        org_id=body.get("org_id", ""),
    )
    log_operation(username=user.username, action="创建文案包资产",
                  target_type="asset_copy_pack", target_id=str(row["id"]))
    return {"data": row}


@router.put("/copy-packs/{asset_id}")
async def update_copy_pack(asset_id: int, body: dict = Body(...), user: User = Depends(get_current_user)):
    row = asset_copy_pack_repository.update(asset_id, **body)
    if not row:
        return {"error": "文案包不存在"}
    log_operation(username=user.username, action="更新文案包资产",
                  target_type="asset_copy_pack", target_id=str(asset_id))
    return {"data": row}


@router.delete("/copy-packs/{asset_id}")
async def delete_copy_pack(asset_id: int, user: User = Depends(get_current_user)):
    ok = asset_copy_pack_repository.delete(asset_id)
    if not ok:
        return {"error": "文案包不存在"}
    log_operation(username=user.username, action="删除文案包资产",
                  target_type="asset_copy_pack", target_id=str(asset_id))
    return {"ok": True}


@router.post("/copy-packs/{asset_id}/toggle")
async def toggle_copy_pack(asset_id: int, user: User = Depends(get_current_user)):
    row = asset_copy_pack_repository.toggle_status(asset_id)
    if not row:
        return {"error": "文案包不存在"}
    log_operation(username=user.username, action=f"{'启用' if row['status'] == 'active' else '停用'}文案包资产",
                  target_type="asset_copy_pack", target_id=str(asset_id))
    return {"data": row}


# ═══════════════════════════════════════════════════════════
#  地区组库
# ═══════════════════════════════════════════════════════════

@router.get("/region-groups")
async def list_region_groups(
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    _user: User = Depends(get_current_user),
):
    rows = asset_region_group_repository.list_all(status=status, keyword=keyword)
    return {"data": rows}


@router.get("/region-groups/{asset_id}")
async def get_region_group(asset_id: int, _user: User = Depends(get_current_user)):
    row = asset_region_group_repository.get_by_id(asset_id)
    if not row:
        return {"error": "地区组不存在"}
    return {"data": row}


@router.post("/region-groups")
async def create_region_group(body: dict = Body(...), user: User = Depends(get_current_user)):
    codes = body.get("country_codes", [])
    row = asset_region_group_repository.create(
        name=body.get("name", ""),
        country_codes=codes,
        language_hint=body.get("language_hint", ""),
        remark=body.get("remark", ""),
        created_by=user.username,
        org_id=body.get("org_id", ""),
    )
    log_operation(username=user.username, action="创建地区组资产",
                  target_type="asset_region_group", target_id=str(row["id"]))
    return {"data": row}


@router.put("/region-groups/{asset_id}")
async def update_region_group(asset_id: int, body: dict = Body(...), user: User = Depends(get_current_user)):
    row = asset_region_group_repository.update(asset_id, **body)
    if not row:
        return {"error": "地区组不存在"}
    log_operation(username=user.username, action="更新地区组资产",
                  target_type="asset_region_group", target_id=str(asset_id))
    return {"data": row}


@router.delete("/region-groups/{asset_id}")
async def delete_region_group(asset_id: int, user: User = Depends(get_current_user)):
    ok = asset_region_group_repository.delete(asset_id)
    if not ok:
        return {"error": "地区组不存在"}
    log_operation(username=user.username, action="删除地区组资产",
                  target_type="asset_region_group", target_id=str(asset_id))
    return {"ok": True}


@router.post("/region-groups/{asset_id}/toggle")
async def toggle_region_group(asset_id: int, user: User = Depends(get_current_user)):
    row = asset_region_group_repository.toggle_status(asset_id)
    if not row:
        return {"error": "地区组不存在"}
    log_operation(username=user.username, action=f"{'启用' if row['status'] == 'active' else '停用'}地区组资产",
                  target_type="asset_region_group", target_id=str(asset_id))
    return {"data": row}
