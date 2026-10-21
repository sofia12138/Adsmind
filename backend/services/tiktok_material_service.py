"""TikTok 素材上传 Service — 处理上传调度、时长判断、TikTok API 调用、状态管理"""
from __future__ import annotations

import tempfile
from pathlib import Path

from loguru import logger

from repositories import biz_account_repository
from repositories import tiktok_material_repository
from tiktok_ads.api.client import TikTokClient, TikTokApiError
from tiktok_ads.api.creative import CreativeService
from config import get_settings

DURATION_THRESHOLD_SEC = 600  # 10 分钟

# record_id → {"sent": bytes_sent, "total": total_bytes, "pct": 0-100, "phase": "tiktok"}
_tiktok_progress: dict[int, dict] = {}


def get_tiktok_progress(record_id: int) -> dict | None:
    return _tiktok_progress.get(record_id)


def _get_token_for_advertiser(advertiser_id: str) -> str:
    """阶段 2：通过统一凭证服务取 token（加密表 → 旧明文 → .env 兑底）。"""
    from services.credential_service import resolve_access_token
    return resolve_access_token("tiktok", account_id=advertiser_id) or ""


def _determine_upload_channel(duration_sec: float | None) -> str:
    if duration_sec is not None and duration_sec > DURATION_THRESHOLD_SEC:
        return "api"
    return "manual"


def _build_ad_usage(duration_sec: float | None) -> tuple[int, str]:
    """返回 (can_use_for_ad, ad_usage_note)"""
    if duration_sec is not None and duration_sec > DURATION_THRESHOLD_SEC:
        return 0, "已通过 API 入库，是否可直接用于投放以 TikTok 广告规格和账户能力为准"
    return 1, ""


async def upload_video(
    *,
    advertiser_id: str,
    file_path: str,
    file_name: str,
    file_size: int,
    duration_sec: float | None,
    created_by: str = "",
    file_md5: str | None = None,
) -> dict:
    """核心上传流程：创建记录 → 调用 TikTok API → 补全信息 → 更新状态。

    file_md5 由路由层在接收文件时同步算出，传入后可避免在 creative 层再扫一遍文件。
    """

    from services.credential_service import _check_account_scope
    from core.isolation import tenant_id
    _check_account_scope(tenant_id(), 'tiktok', advertiser_id)
    upload_channel = _determine_upload_channel(duration_sec)
    can_use, usage_note = _build_ad_usage(duration_sec)

    record_id = tiktok_material_repository.create({
        "advertiser_id": advertiser_id,
        "local_file_name": file_name,
        "file_size_bytes": file_size,
        "duration_sec": duration_sec,
        "upload_channel": upload_channel,
        "upload_status": "uploading",
        "can_use_for_ad": can_use,
        "ad_usage_note": usage_note,
        "created_by": created_by,
    })
    logger.info(
        f"[tiktok-material] 创建上传记录: id={record_id}, channel={upload_channel}, "
        f"duration={duration_sec}s, size={file_size}"
    )

    token = _get_token_for_advertiser(advertiser_id)
    client = TikTokClient(access_token=token, account_id=advertiser_id)
    svc = CreativeService(client=client, advertiser_id=advertiser_id)

    def _on_progress(sent: int, total: int) -> None:
        pct = int(sent * 100 / total) if total else 0
        _tiktok_progress[record_id] = {"sent": sent, "total": total, "pct": pct, "phase": "tiktok"}

    try:
        upload_data = await svc.upload_video_by_file(
            file_path, file_name, on_progress=_on_progress, file_md5=file_md5,
        )
    except TikTokApiError as e:
        logger.error(
            f"[tiktok-material] TikTok API 上传失败: record={record_id}, "
            f"advertiser={advertiser_id}, file={file_name}, channel={upload_channel}, err={e}"
        )
        tiktok_material_repository.update_status(
            record_id, "failed",
            error_code=str(e.code),
            error_message=e.message,
        )
        _tiktok_progress.pop(record_id, None)
        return _get_record_dict(record_id)
    except BaseException as e:
        logger.error(
            f"[tiktok-material] 上传异常: record={record_id}, "
            f"advertiser={advertiser_id}, file={file_name}, channel={upload_channel}, "
            f"type={type(e).__name__}, err={e}"
        )
        try:
            tiktok_material_repository.update_status(
                record_id, "failed",
                error_code=type(e).__name__,
                error_message=str(e)[:500],
            )
        except Exception:
            logger.error(f"[tiktok-material] 回写 failed 状态也失败: record={record_id}")
        _tiktok_progress.pop(record_id, None)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return _get_record_dict(record_id)

    # upload_data 已由 creative 层标准化为 dict，但防御性二次检查
    if isinstance(upload_data, list):
        upload_data = upload_data[0] if upload_data else {}
    if not isinstance(upload_data, dict):
        upload_data = {}

    video_id = upload_data.get("video_id", "")
    if not video_id:
        tiktok_material_repository.update_status(
            record_id, "failed",
            error_code="NO_VIDEO_ID",
            error_message=f"TikTok API 未返回 video_id: {str(upload_data)[:300]}",
        )
        _tiktok_progress.pop(record_id, None)
        return _get_record_dict(record_id)

    update_kwargs: dict = {
        "tiktok_video_id": video_id,
    }

    # 优先从上传响应中提取元数据（TikTok upload 接口已返回 width/duration/preview_url）
    if upload_data.get("width"):
        update_kwargs["tiktok_width"] = upload_data["width"]
    if upload_data.get("height"):
        update_kwargs["tiktok_height"] = upload_data["height"]
    if upload_data.get("format"):
        update_kwargs["tiktok_format"] = upload_data["format"]
    if upload_data.get("preview_url"):
        update_kwargs["tiktok_url"] = upload_data["preview_url"]
    if upload_data.get("file_name"):
        update_kwargs["tiktok_file_name"] = upload_data["file_name"]
    api_duration = upload_data.get("duration")
    if api_duration:
        update_kwargs["duration_sec"] = float(api_duration)
        can_use, usage_note = _build_ad_usage(float(api_duration))
        update_kwargs["can_use_for_ad"] = can_use
        update_kwargs["ad_usage_note"] = usage_note

    # 兜底：如果上传响应缺少元数据，再调 info 接口补全
    if "tiktok_width" not in update_kwargs:
        try:
            info_list = await svc.get_video_info_detail([video_id])
            if info_list:
                vi = info_list[0] if isinstance(info_list, list) else info_list
                if isinstance(vi, dict):
                    update_kwargs.setdefault("tiktok_file_name", vi.get("file_name", ""))
                    update_kwargs.setdefault("tiktok_url", vi.get("preview_url") or vi.get("video_cover_url", ""))
                    update_kwargs.setdefault("tiktok_width", vi.get("width"))
                    update_kwargs.setdefault("tiktok_height", vi.get("height"))
                    update_kwargs.setdefault("tiktok_format", vi.get("format", ""))
                    api_dur = vi.get("duration")
                    if api_dur and "duration_sec" not in update_kwargs:
                        update_kwargs["duration_sec"] = float(api_dur)
                        can_use, usage_note = _build_ad_usage(float(api_dur))
                        update_kwargs["can_use_for_ad"] = can_use
                        update_kwargs["ad_usage_note"] = usage_note
        except Exception as e:
            logger.warning(f"[tiktok-material] 获取视频信息失败（不阻塞）: record={record_id}, err={e}")

    tiktok_material_repository.update_status(record_id, "success", **update_kwargs)
    _tiktok_progress.pop(record_id, None)
    logger.info(f"[tiktok-material] 上传完成: record={record_id}, video_id={video_id}")
    return _get_record_dict(record_id)


def get_material(record_id: int) -> dict | None:
    return _get_record_dict(record_id)


def list_materials(
    *,
    advertiser_id: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    rows, total = tiktok_material_repository.list_all(
        advertiser_id=advertiser_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _get_record_dict(record_id: int) -> dict:
    row = tiktok_material_repository.get_by_id(record_id)
    if not row:
        return {"id": record_id, "upload_status": "unknown"}
    return _row_to_dict(row)


def _row_to_dict(row: dict) -> dict:
    """将数据库行转为 API 友好的 dict，上传中的记录注入实时进度"""
    r = dict(row)
    for k in ("created_at", "updated_at"):
        if r.get(k):
            r[k] = str(r[k])
    if r.get("duration_sec") is not None:
        r["duration_sec"] = float(r["duration_sec"])
    r["can_use_for_ad"] = bool(r.get("can_use_for_ad"))
    prog = _tiktok_progress.get(r.get("id"))
    if prog:
        r["tiktok_progress"] = prog
    return r
