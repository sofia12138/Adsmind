"""优化师名单配置路由"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from plugins.optimizer import repository_directory as optimizer_directory_repository

router = APIRouter(prefix="/optimizer-directory", tags=["优化师名单配置"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class DirectoryCreateBody(BaseModel):
    optimizer_name: str
    optimizer_code: str
    aliases: str = ""
    is_active: int = 1
    remark: str = ""


class DirectoryUpdateBody(BaseModel):
    id: int
    optimizer_name: Optional[str] = None
    optimizer_code: Optional[str] = None
    aliases: Optional[str] = None
    is_active: Optional[int] = None
    remark: Optional[str] = None


class ToggleStatusBody(BaseModel):
    id: int
    is_active: int


class AssignSampleBody(BaseModel):
    optimizer_name_raw: str
    optimizer_id: int


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _clean_aliases(raw: str) -> str:
    """trim + 去重"""
    parts = [a.strip() for a in raw.split(",") if a.strip()]
    seen = set()
    result = []
    for p in parts:
        key = p.upper()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return ",".join(result)


# ---------------------------------------------------------------------------
# 名单 CRUD
# ---------------------------------------------------------------------------

@router.get("/list")
async def list_directory(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    is_active: Optional[int] = Query(None, description="状态: 1=启用 0=停用"),
):
    rows = await asyncio.to_thread(
        optimizer_directory_repository.get_all,
        keyword=keyword,
        is_active=is_active,
    )
    result = []
    for r in rows:
        result.append({
            "id":             r["id"],
            "optimizer_name": r.get("optimizer_name", ""),
            "optimizer_code": r.get("optimizer_code", ""),
            "aliases":        r.get("aliases", ""),
            "is_active":      r.get("is_active", 1),
            "remark":         r.get("remark", ""),
            "created_at":     str(r.get("created_at", "")),
            "updated_at":     str(r.get("updated_at", "")),
        })
    return {"code": 0, "message": "ok", "data": result}


@router.post("/create")
async def create_directory(body: DirectoryCreateBody):
    if not body.optimizer_name.strip():
        raise HTTPException(400, "optimizer_name 不能为空")
    if not body.optimizer_code.strip():
        raise HTTPException(400, "optimizer_code 不能为空")

    exists = await asyncio.to_thread(
        optimizer_directory_repository.code_exists,
        body.optimizer_code.strip(),
    )
    if exists:
        raise HTTPException(400, f"optimizer_code '{body.optimizer_code}' 已存在")

    data = body.model_dump()
    data["optimizer_name"] = data["optimizer_name"].strip()
    data["optimizer_code"] = data["optimizer_code"].strip()
    data["aliases"] = _clean_aliases(data.get("aliases", ""))

    new_id = await asyncio.to_thread(optimizer_directory_repository.create, data)
    return {"code": 0, "message": "ok", "data": {"id": new_id}}


@router.put("/update")
async def update_directory(body: DirectoryUpdateBody):
    data = {}
    if body.optimizer_name is not None:
        if not body.optimizer_name.strip():
            raise HTTPException(400, "optimizer_name 不能为空")
        data["optimizer_name"] = body.optimizer_name.strip()
    if body.optimizer_code is not None:
        if not body.optimizer_code.strip():
            raise HTTPException(400, "optimizer_code 不能为空")
        exists = await asyncio.to_thread(
            optimizer_directory_repository.code_exists,
            body.optimizer_code.strip(),
            exclude_id=body.id,
        )
        if exists:
            raise HTTPException(400, f"optimizer_code '{body.optimizer_code}' 已被其他记录使用")
        data["optimizer_code"] = body.optimizer_code.strip()
    if body.aliases is not None:
        data["aliases"] = _clean_aliases(body.aliases)
    if body.is_active is not None:
        data["is_active"] = body.is_active
    if body.remark is not None:
        data["remark"] = body.remark.strip()

    if not data:
        raise HTTPException(400, "未提供任何更新字段")

    cnt = await asyncio.to_thread(optimizer_directory_repository.update, body.id, data)
    if cnt == 0:
        raise HTTPException(404, f"优化师 {body.id} 不存在")
    return {"code": 0, "message": "ok", "data": {"affected": cnt}}


@router.post("/toggle-status")
async def toggle_status(body: ToggleStatusBody):
    cnt = await asyncio.to_thread(
        optimizer_directory_repository.toggle_status,
        body.id, body.is_active,
    )
    if cnt == 0:
        raise HTTPException(404, f"优化师 {body.id} 不存在")
    return {"code": 0, "message": "ok", "data": {"affected": cnt}}


@router.delete("/delete")
async def delete_directory(id: int = Query(..., description="优化师ID")):
    cnt = await asyncio.to_thread(optimizer_directory_repository.delete, id)
    if cnt == 0:
        raise HTTPException(404, f"优化师 {id} 不存在")
    return {"code": 0, "message": "ok", "data": {"deleted": cnt}}


# ---------------------------------------------------------------------------
# 未识别样本
# ---------------------------------------------------------------------------

@router.get("/unassigned-samples")
async def unassigned_samples(
    limit: int = Query(200, description="返回条数上限"),
):
    rows = await asyncio.to_thread(
        optimizer_directory_repository.get_unassigned_samples,
        limit=limit,
    )
    result = []
    for r in rows:
        result.append({
            "optimizer_name_raw": r.get("optimizer_name_raw", ""),
            "occurrence_count":   int(r.get("occurrence_count") or 0),
            "total_spend":        round(float(r.get("total_spend") or 0), 2),
            "last_seen_at":       str(r.get("last_seen_at", "")),
        })
    return {"code": 0, "message": "ok", "data": result}


@router.post("/assign-sample")
async def assign_sample(body: AssignSampleBody):
    """将未识别样本匹配到指定优化师"""
    if not body.optimizer_name_raw.strip():
        raise HTTPException(400, "optimizer_name_raw 不能为空")

    cnt = await asyncio.to_thread(
        optimizer_directory_repository.assign_sample,
        body.optimizer_name_raw.strip(),
        body.optimizer_id,
    )
    return {"code": 0, "message": "ok", "data": {"affected": cnt}}


# ---------------------------------------------------------------------------
# 重跑映射
# ---------------------------------------------------------------------------

@router.post("/rebuild-mapping")
async def rebuild_mapping():
    """重跑近 30 天优化师映射和汇总"""
    from datetime import date, timedelta
    from plugins.optimizer.sync_job import run as sync_run

    end = date.today()
    start = end - timedelta(days=30)
    result = await asyncio.to_thread(sync_run, str(start), str(end))
    return {"code": 0, "message": "ok", "data": result}
