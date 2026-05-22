"""TikTok 素材上传路由 — 上传 / 查询 / 列表"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from loguru import logger

from auth import get_current_user, User
from services import tiktok_material_service

router = APIRouter(prefix="/materials/tiktok", tags=["TikTok 素材上传"])

_ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_VIDEO_MAX = 1024 * 1024 * 1024  # 1 GB
_RECV_CHUNK = 4 * 1024 * 1024  # 4MB，减少 syscall 次数

# 优先使用内存盘（Linux tmpfs），避免落到云盘；Windows / 无 /dev/shm 时回退默认 tmp
_TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None


@router.post("/upload")
async def upload_video(
    advertiser_id: str = Form(..., description="TikTok 广告主 ID"),
    file: UploadFile = File(...),
    file_name: Optional[str] = Form(None, description="原始文件名（前端显式传入，避免 multipart 中文乱码）"),
    duration_sec: Optional[float] = Form(None, description="视频时长（秒），前端读取后传入"),
    _user: User = Depends(get_current_user),
):
    """上传视频至 TikTok Asset Library。
    前端读取视频时长后传入 duration_sec；>600s 自动走 API 上传模式。
    """
    t0 = time.time()
    filename = file_name or file.filename or "upload.mp4"
    logger.info(
        f"[tiktok-materials] 上传请求: advertiser={advertiser_id}, file={filename}, "
        f"duration={duration_sec}, user={_user.username}"
    )

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXT:
        return JSONResponse(content={
            "success": False,
            "error": f"不支持的视频格式 {ext}，支持: {', '.join(sorted(_ALLOWED_VIDEO_EXT))}",
        })

    tmp_path = None
    try:
        md5 = hashlib.md5()
        recv_t0 = time.time()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=_TMP_DIR) as tmp:
            tmp_path = tmp.name
            file_size = 0
            while True:
                chunk = await file.read(_RECV_CHUNK)
                if not chunk:
                    break
                tmp.write(chunk)
                md5.update(chunk)
                file_size += len(chunk)
        precomputed_md5 = md5.hexdigest()

        if file_size == 0:
            return JSONResponse(content={"success": False, "error": "接收到的文件为空（0 字节）"})
        if file_size > _VIDEO_MAX:
            return JSONResponse(content={
                "success": False,
                "error": f"文件 {file_size / 1024 / 1024:.0f}MB 超过 1GB 限制",
            })

        recv_ms = int((time.time() - recv_t0) * 1000)
        logger.info(
            f"[tiktok-materials] 文件缓存完成: size={file_size} "
            f"({file_size / 1024 / 1024:.1f}MB), duration={duration_sec}s, "
            f"recv={recv_ms}ms, tmp_dir={_TMP_DIR or 'system_default'}, md5={precomputed_md5}"
        )

        record = await tiktok_material_service.upload_video(
            advertiser_id=advertiser_id,
            file_path=tmp_path,
            file_name=filename,
            file_size=file_size,
            duration_sec=duration_sec,
            created_by=_user.username,
            file_md5=precomputed_md5,
        )

        elapsed = int((time.time() - t0) * 1000)
        success = record.get("upload_status") == "success"
        logger.info(
            f"[tiktok-materials] 上传{'成功' if success else '失败'}: "
            f"record_id={record.get('id')}, elapsed={elapsed}ms"
        )

        return JSONResponse(content={
            "success": success,
            "data": record,
            "upload_time_ms": elapsed,
        })

    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error(f"[tiktok-materials] 上传异常: {type(e).__name__}: {e}, elapsed={elapsed}ms")
        return JSONResponse(content={
            "success": False, "error": f"上传异常: {e}",
        })
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@router.get("/account-library")
async def list_account_library_videos(
    advertiser_id: str = Query(..., description="TikTok 广告主 ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="按文件名/video_id 模糊匹配（前端层做）"),
    _user: User = Depends(get_current_user),
):
    """拉取 TikTok 账户内已上传素材（含手动在广告平台上传的素材）。
    封装 TikTok API: GET file/video/ad/search/

    返回: { data: { items: [...], page, page_size, total, has_more } }
    items 字段: video_id, file_name, video_cover_url, duration, width, height,
              format, size, create_time, material_id(可选)
    """
    from repositories import biz_account_repository
    from tiktok_ads.api.client import TikTokClient
    from tiktok_ads.api.creative import CreativeService

    # 阶段 2：统一从加密凭证服务读 token
    from services.credential_service import resolve_access_token
    _token = resolve_access_token("tiktok", account_id=advertiser_id)
    if not _token:
        return JSONResponse(status_code=400, content={
            "error": f"未找到 advertiser_id={advertiser_id} 对应的 TikTok access_token，请先完成 OAuth 授权",
        })

    client = TikTokClient(access_token=_token, account_id=advertiser_id)
    svc = CreativeService(client=client, advertiser_id=advertiser_id)

    try:
        raw = await svc.search_videos(page=page, page_size=page_size)
    except Exception as e:
        logger.warning(f"[account-library] TikTok search_videos 失败: {e}")
        return JSONResponse(status_code=502, content={"error": f"TikTok 接口异常: {e}"})

    raw_list = raw.get("list") or []
    page_info = raw.get("page_info") or {}
    total = int(page_info.get("total_number") or 0)
    total_page = int(page_info.get("total_page") or 0)

    items = []
    for v in raw_list:
        if not isinstance(v, dict):
            continue
        items.append({
            "video_id": v.get("video_id") or "",
            "file_name": v.get("file_name") or v.get("material_name") or "",
            "video_cover_url": v.get("video_cover_url") or v.get("poster_url") or v.get("preview_url") or "",
            "duration": v.get("duration") or v.get("video_length") or 0,
            "width": v.get("width") or 0,
            "height": v.get("height") or 0,
            "format": v.get("format") or v.get("file_format") or "",
            "size": v.get("size") or 0,
            "create_time": v.get("create_time") or "",
            "material_id": v.get("material_id") or "",
        })

    # 关键词在前端层匹配（避免 TikTok 端不支持 keyword 参数）；这里仅返回服务端过滤后的字段
    if keyword:
        kw = keyword.strip().lower()
        items = [it for it in items if kw in (it["file_name"] or "").lower() or kw in (it["video_id"] or "").lower()]

    has_more = page < total_page if total_page else len(raw_list) >= page_size
    return {
        "data": {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_page": total_page,
            "has_more": has_more,
        }
    }


@router.delete("/{material_id}")
async def delete_material(
    material_id: int,
    _user: User = Depends(get_current_user),
):
    """删除失败/待上传的记录（幂等：已删除的记录也返回成功）"""
    record = tiktok_material_service.get_material(material_id)
    if not record:
        return {"success": True}
    if record.get("upload_status") not in ("failed", "pending"):
        return JSONResponse(status_code=400, content={
            "error": f"仅允许删除失败/待上传状态的记录，当前状态: {record.get('upload_status')}",
        })
    from repositories import tiktok_material_repository
    tiktok_material_repository.delete_by_id(material_id)
    return {"success": True}


@router.get("/{material_id}")
async def get_material(
    material_id: int,
    _user: User = Depends(get_current_user),
):
    """查询单条上传记录"""
    record = tiktok_material_service.get_material(material_id)
    if not record:
        return JSONResponse(status_code=404, content={"error": "记录不存在"})
    return {"data": record}


@router.get("")
@router.get("/", include_in_schema=False)
async def list_materials(
    advertiser_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending/uploading/success/failed"),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
):
    """分页查询上传记录列表"""
    result = tiktok_material_service.list_materials(
        advertiser_id=advertiser_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return {"data": result}
