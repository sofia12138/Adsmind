"""Meta 资产接口 — 主页列表、Pixel列表、图片/视频上传"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from loguru import logger

from auth import get_current_user, User
from meta_ads.api.client import MetaClient
from repositories import biz_account_repository

router = APIRouter(prefix="/meta/assets", tags=["Meta 资产"])

_IMAGE_MAX = 30 * 1024 * 1024      # 30 MB
_VIDEO_MAX = 500 * 1024 * 1024     # 500 MB
_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _get_token_for_account(ad_account_id: str) -> str:
    """根据 ad_account_id 获取 access_token（阶段 2：走统一凭证服务）。

    优先级：加密表 → 旧明文兼容 → .env 默认值。
    """
    from services.credential_service import resolve_access_token
    return resolve_access_token("meta", account_id=ad_account_id) or ""


# ── 主页列表 ──────────────────────────────────────────────

@router.get("/pages")
async def list_pages(
    ad_account_id: str = Query(..., description="Meta 广告账户 ID，如 act_123456"),
    _user: User = Depends(get_current_user),
):
    """获取当前 token 可投放的 Facebook 主页列表"""
    token = _get_token_for_account(ad_account_id)
    client = MetaClient(access_token=token)
    try:
        data = await client.get("me/accounts", {
            "fields": "id,name,category",
            "limit": 100,
        })
        pages = [
            {"id": p["id"], "name": p.get("name", p["id"])}
            for p in data.get("data", [])
        ]
        return {"data": pages}
    except Exception as e:
        logger.error(f"[meta-assets] 拉取主页列表失败: ad_account={ad_account_id}, err={e}")
        return {"data": [], "error": str(e)}


# ── Pixel 列表 ────────────────────────────────────────────

@router.get("/pixels")
async def list_pixels(
    ad_account_id: str = Query(..., description="Meta 广告账户 ID，如 act_123456"),
    _user: User = Depends(get_current_user),
):
    """获取广告账户下可用的 Pixel 列表"""
    token = _get_token_for_account(ad_account_id)
    client = MetaClient(access_token=token)
    try:
        data = await client.get(f"{ad_account_id}/adspixels", {
            "fields": "id,name,last_fired_time",
            "limit": 100,
        })
        pixels = [
            {"id": p["id"], "name": p.get("name", p["id"])}
            for p in data.get("data", [])
        ]
        return {"data": pixels}
    except Exception as e:
        logger.error(f"[meta-assets] 拉取 Pixel 列表失败: ad_account={ad_account_id}, err={e}")
        return {"data": [], "error": str(e)}


# ── 账户已上传素材列表（adimages / advideos） ────────────────
#
# Meta 不像 TikTok 一次返回视频+图片；分两类资源：
#   GET act_xxx/advideos  → list[{id, title, thumbnails, length, ...}]
#   GET act_xxx/adimages  → list[{hash, name, url, width, height, ...}]
# 前端用 type=video|image|all 控制要哪些。
# cursor: Graph API 的 paging.cursors.after；返回 next_cursor 让前端续翻。
# keyword: 客户端层面的本页过滤（Graph 不支持 name 模糊搜索）。

@router.get("/list")
async def list_account_assets(
    ad_account_id: str = Query(..., description="Meta 广告账户 ID，如 act_123456"),
    type: str = Query("all", description="video / image / all"),
    cursor: str | None = Query(None, description="分页游标（Graph paging.cursors.after），仅作用于单一类型"),
    keyword: str | None = Query(None, description="按 name/title 模糊匹配（仅当前页）"),
    limit: int = Query(25, ge=1, le=100),
    _user: User = Depends(get_current_user),
):
    """拉取广告账户内已上传素材（视频 / 图片），含手动在 Meta 平台上传的素材。
    返回结构: { data: { items: [...], video_cursor?, image_cursor?, has_more } }
    items 字段统一: type/name/source/preview_url/thumbnail_url/video_id?/image_hash?/meta_asset_id/created_time
    """
    type = (type or "all").lower()
    if type not in ("video", "image", "all"):
        return JSONResponse(status_code=400, content={"error": "type 必须是 video / image / all"})

    token = _get_token_for_account(ad_account_id)
    client = MetaClient(access_token=token)

    items: list[dict] = []
    video_cursor: str | None = None
    image_cursor: str | None = None
    errors: list[str] = []

    # ── 视频 ──
    if type in ("video", "all"):
        try:
            params: dict = {
                "fields": "id,title,thumbnails{uri},length,created_time,format",
                "limit": limit,
            }
            # 当 type=all 时，cursor 不再适用单一类型；前端要分页时建议指定 type=video
            if cursor and type == "video":
                params["after"] = cursor
            data = await client.get(f"{ad_account_id}/advideos", params)
            for v in (data.get("data") or []):
                vid = str(v.get("id") or "")
                if not vid:
                    continue
                title = v.get("title") or vid
                thumbs = ((v.get("thumbnails") or {}).get("data") or [])
                thumb_url = thumbs[0].get("uri") if thumbs else ""
                items.append({
                    "type": "video",
                    "source": "account_asset",
                    "name": title,
                    "video_id": vid,
                    "meta_asset_id": vid,
                    "preview_url": thumb_url,
                    "thumbnail_url": thumb_url,
                    "duration_sec": v.get("length") or 0,
                    "created_time": v.get("created_time") or "",
                })
            video_cursor = ((data.get("paging") or {}).get("cursors") or {}).get("after") or None
            # 当 paging.next 不存在时，认为没有下一页
            if not (data.get("paging") or {}).get("next"):
                video_cursor = None
        except Exception as e:
            logger.warning(f"[meta-assets] 拉取账户视频素材失败 ad_account={ad_account_id}: {e}")
            errors.append(f"video: {e}")

    # ── 图片 ──
    if type in ("image", "all"):
        try:
            params = {
                "fields": "hash,name,url,permalink_url,width,height,created_time",
                "limit": limit,
            }
            if cursor and type == "image":
                params["after"] = cursor
            data = await client.get(f"{ad_account_id}/adimages", params)
            for im in (data.get("data") or []):
                h = str(im.get("hash") or "")
                if not h:
                    continue
                url = im.get("url") or im.get("permalink_url") or ""
                items.append({
                    "type": "image",
                    "source": "account_asset",
                    "name": im.get("name") or h,
                    "image_hash": h,
                    "meta_asset_id": h,
                    "preview_url": url,
                    "thumbnail_url": url,
                    "width": im.get("width") or 0,
                    "height": im.get("height") or 0,
                    "created_time": im.get("created_time") or "",
                })
            image_cursor = ((data.get("paging") or {}).get("cursors") or {}).get("after") or None
            if not (data.get("paging") or {}).get("next"):
                image_cursor = None
        except Exception as e:
            logger.warning(f"[meta-assets] 拉取账户图片素材失败 ad_account={ad_account_id}: {e}")
            errors.append(f"image: {e}")

    # 关键词过滤（Graph 不支持 name 模糊搜索，只在当前页生效）
    if keyword:
        kw = keyword.strip().lower()
        items = [it for it in items if kw in (it.get("name") or "").lower() or kw in (it.get("meta_asset_id") or "").lower()]

    has_more = bool(video_cursor or image_cursor)
    resp: dict = {
        "data": {
            "items": items,
            "video_cursor": video_cursor,
            "image_cursor": image_cursor,
            "has_more": has_more,
        }
    }
    if errors and not items:
        resp["error"] = "; ".join(errors)
    return resp


# ── 图片上传 ──────────────────────────────────────────────

@router.post("/upload-image")
async def upload_image(
    request: Request,
    ad_account_id: str = Form(...),
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
):
    """上传图片到 Meta，返回 image_hash"""
    t0 = time.time()
    filename = file.filename or "upload.jpg"
    content_type = request.headers.get("content-type", "unknown")
    logger.info(
        f"[meta-assets] 图片上传请求: account={ad_account_id}, file={filename}, "
        f"content_type={content_type[:80]}, user={_user.username}"
    )

    try:
        token = _get_token_for_account(ad_account_id)
    except Exception as e:
        logger.error(f"[meta-assets] 获取 token 失败: {e}")
        return JSONResponse(content={"success": False, "error": f"获取账户凭证失败: {e}"})

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXT:
        return JSONResponse(content={
            "success": False,
            "error": f"不支持的图片格式 {ext}，支持: {', '.join(sorted(_ALLOWED_IMAGE_EXT))}",
        })

    try:
        contents = await file.read()
        file_size = len(contents)
        if file_size == 0:
            return JSONResponse(content={"success": False, "error": "接收到的文件为空（0 字节），请检查上传"})
        if file_size > _IMAGE_MAX:
            return JSONResponse(content={
                "success": False,
                "error": f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过 30MB 限制",
            })

        logger.info(f"[meta-assets] 图片文件读取完成: size={file_size} ({file_size / 1024 / 1024:.1f}MB)")

        import httpx
        url = f"https://graph.facebook.com/v21.0/{ad_account_id}/adimages"

        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(url, data={"access_token": token}, files={"filename": (filename, contents)})

        elapsed = int((time.time() - t0) * 1000)

        resp_text = resp.text
        if not resp_text.strip():
            logger.error(f"[meta-assets] Meta API 返回空响应体, status={resp.status_code}")
            return JSONResponse(content={
                "success": False, "error": f"Meta API 返回空响应 (HTTP {resp.status_code})",
            })

        try:
            result = resp.json()
        except Exception:
            preview = resp_text[:300]
            logger.error(f"[meta-assets] Meta API 返回非 JSON: {preview}")
            return JSONResponse(content={
                "success": False,
                "error": f"Meta API 返回了非 JSON 响应 (HTTP {resp.status_code})",
            })

        if "error" in result:
            err_msg = result["error"].get("message", "Unknown error")
            err_code = result["error"].get("code", "")
            logger.error(f"[meta-assets] 图片上传失败: code={err_code}, msg={err_msg} ({elapsed}ms)")
            return JSONResponse(content={
                "success": False,
                "error": f"[{err_code}] {err_msg}" if err_code else err_msg,
            })

        images = result.get("images", {})
        if not images:
            return JSONResponse(content={"success": False, "error": "Meta API 未返回 image_hash"})

        first_key = next(iter(images))
        image_hash = images[first_key].get("hash", "")
        logger.info(f"[meta-assets] 图片上传成功: hash={image_hash}, size={file_size}, elapsed={elapsed}ms")
        return JSONResponse(content={
            "success": True, "image_hash": image_hash, "name": filename,
            "size": file_size, "upload_time_ms": elapsed,
        })

    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error(f"[meta-assets] 图片上传异常: type={type(e).__name__}, msg={e}, elapsed={elapsed}ms")
        return JSONResponse(content={"success": False, "error": f"上传异常: {e}"})


# ── 视频上传 ──────────────────────────────────────────────

import asyncio

_CHUNK_MB = 5
_CHUNK_SIZE = _CHUNK_MB * 1024 * 1024
_SIMPLE_THRESHOLD = 50 * 1024 * 1024   # ≤50 MB 走简单上传
_RETRYABLE_CODES = {1, 2, 4, 17, 341}  # Meta 临时性错误码
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 4, 8]              # 秒


def _parse_meta_resp(resp) -> tuple[dict | None, dict]:
    """解析 Meta API 响应，返回 (data, error_info)。error_info 为空 dict 表示成功"""
    info: dict = {"http_status": resp.status_code, "body_preview": ""}
    text = resp.text
    info["body_preview"] = text[:300] if text else ""

    if not text.strip():
        return None, {**info, "error": f"Meta API 返回空响应 (HTTP {resp.status_code})"}
    try:
        data = resp.json()
    except Exception:
        return None, {**info, "error": f"Meta API 返回非 JSON (HTTP {resp.status_code}): {text[:200]}"}

    if "error" in data:
        e = data["error"]
        code = e.get("code", "")
        msg = e.get("message", "Unknown error")
        subcode = e.get("error_subcode", "")
        fbtrace = e.get("fbtrace_id", "")
        err_str = f"[{code}] {msg}"
        if subcode:
            err_str += f" (subcode={subcode})"
        if fbtrace:
            err_str += f" (fbtrace={fbtrace})"
        return None, {**info, "error": err_str, "code": code, "subcode": subcode,
                      "fbtrace_id": fbtrace, "is_retryable": int(code) in _RETRYABLE_CODES if code else False}

    return data, {}


def _build_url(ad_account_id: str) -> str:
    return f"https://graph.facebook.com/v21.0/{ad_account_id}/advideos"


async def _meta_post_with_retry(http, url: str, phase: str, **kwargs) -> tuple[dict | None, dict, int]:
    """对 Meta API POST 进行带重试的调用。返回 (data, err_info, attempts_used)"""
    last_err: dict = {}
    for attempt in range(1, _MAX_RETRIES + 1):
        resp = await http.post(url, **kwargs)
        data, err_info = _parse_meta_resp(resp)

        if not err_info:
            if attempt > 1:
                logger.info(f"[meta-assets] {phase} 第 {attempt} 次重试成功")
            return data, {}, attempt

        last_err = err_info
        if not err_info.get("is_retryable") or attempt == _MAX_RETRIES:
            logger.error(
                f"[meta-assets] {phase} 最终失败 (attempt={attempt}/{_MAX_RETRIES}): "
                f"error={err_info.get('error')}, http={err_info.get('http_status')}"
            )
            break

        delay = _RETRY_DELAYS[attempt - 1] if attempt - 1 < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
        logger.warning(
            f"[meta-assets] {phase} 可重试错误 (attempt={attempt}/{_MAX_RETRIES}), "
            f"code={err_info.get('code')}, {delay}s 后重试..."
        )
        await asyncio.sleep(delay)

    last_err["retry_count"] = attempt          # type: ignore[possibly-undefined]
    return None, last_err, attempt             # type: ignore[possibly-undefined]


async def _simple_upload_to_meta(
    ad_account_id: str, token: str, tmp_path: str,
    file_size: int, filename: str,
) -> dict:
    """简单上传：单次 POST 整个文件，适用于 ≤50MB 的小视频"""
    import httpx
    url = _build_url(ad_account_id)
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=30.0)

    logger.info(f"[meta-assets] 使用简单上传模式: url={url}, file_size={file_size}")

    async with httpx.AsyncClient(timeout=timeout) as http:
        with open(tmp_path, "rb") as f:
            data, err_info, attempts = await _meta_post_with_retry(
                http, url, "simple-upload",
                data={"access_token": token, "title": filename},
                files={"source": (filename, f)},
            )

    base = {"upload_mode": "simple", "retry_count": attempts}
    if err_info:
        return {**base, "success": False, "stage": "simple-upload",
                "error": err_info.get("error", "上传失败"),
                "meta_response": err_info.get("body_preview", "")}

    video_id = data.get("id", "")
    if not video_id:
        return {**base, "success": False, "stage": "simple-upload",
                "error": f"Meta API 未返回 video_id, response: {str(data)[:200]}"}

    return {**base, "success": True, "video_id": video_id, "chunks": 0}


async def _chunked_upload_to_meta(
    ad_account_id: str, token: str, tmp_path: str,
    file_size: int, filename: str,
) -> dict:
    """Meta Chunked Upload API: start → transfer × N → finish，带重试"""
    import httpx
    url = _build_url(ad_account_id)
    timeout = httpx.Timeout(connect=30.0, read=120.0, write=120.0, pool=30.0)
    total_retries = 0

    logger.info(
        f"[meta-assets] 使用分片上传模式: url={url}, file_size={file_size}, "
        f"chunk_size={_CHUNK_SIZE}, estimated_chunks={file_size // _CHUNK_SIZE + 1}"
    )

    async with httpx.AsyncClient(timeout=timeout) as http:
        # ── Phase 1: start ──
        logger.info(
            f"[meta-assets] chunked start 请求: url={url}, "
            f"upload_phase=start, file_size={file_size}"
        )

        data, err_info, attempts = await _meta_post_with_retry(
            http, url, "chunked-start",
            data={"access_token": token, "upload_phase": "start", "file_size": str(file_size)},
        )
        total_retries += attempts

        if err_info:
            logger.error(
                f"[meta-assets] chunked start 最终失败: "
                f"http_status={err_info.get('http_status')}, "
                f"error={err_info.get('error')}, "
                f"body_preview={err_info.get('body_preview', '')[:200]}"
            )
            return {"success": False, "stage": "start", "upload_mode": "chunked",
                    "retry_count": total_retries,
                    "error": f"分片上传 start 失败: {err_info.get('error')}",
                    "meta_response": err_info.get("body_preview", "")}

        session_id = data.get("upload_session_id")
        video_id = data.get("video_id", "")
        start_offset = int(data.get("start_offset", 0))
        end_offset = int(data.get("end_offset", _CHUNK_SIZE))

        if not session_id:
            logger.error(f"[meta-assets] start 响应缺少 upload_session_id: {str(data)[:300]}")
            return {"success": False, "stage": "start", "upload_mode": "chunked",
                    "retry_count": total_retries,
                    "error": f"Meta API 未返回 upload_session_id, response: {str(data)[:200]}"}

        logger.info(
            f"[meta-assets] 分片会话已建立: session={session_id}, video_id={video_id}, "
            f"first_chunk={start_offset}-{end_offset}"
        )

        # ── Phase 2: transfer × N ──
        chunk_num = 0
        with open(tmp_path, "rb") as f:
            while start_offset < file_size:
                chunk_len = min(end_offset - start_offset, file_size - start_offset)
                f.seek(start_offset)
                chunk_data = f.read(chunk_len)
                chunk_num += 1

                logger.info(
                    f"[meta-assets] 分片 #{chunk_num}: offset={start_offset}-{start_offset + len(chunk_data)}, "
                    f"size={len(chunk_data) / 1024 / 1024:.2f}MB"
                )

                data, err_info, attempts = await _meta_post_with_retry(
                    http, url, f"chunked-transfer-#{chunk_num}",
                    data={
                        "access_token": token,
                        "upload_phase": "transfer",
                        "upload_session_id": session_id,
                        "start_offset": str(start_offset),
                    },
                    files={"video_file_chunk": (filename, chunk_data)},
                )
                total_retries += attempts

                if err_info:
                    return {"success": False, "stage": "transfer", "upload_mode": "chunked",
                            "retry_count": total_retries,
                            "error": f"分片 #{chunk_num} 上传失败: {err_info.get('error')}",
                            "meta_response": err_info.get("body_preview", "")}

                start_offset = int(data.get("start_offset", file_size))
                end_offset = int(data.get("end_offset", file_size))

        logger.info(f"[meta-assets] 全部 {chunk_num} 个分片已上传，开始 finish")

        # ── Phase 3: finish ──
        data, err_info, attempts = await _meta_post_with_retry(
            http, url, "chunked-finish",
            data={
                "access_token": token,
                "upload_phase": "finish",
                "upload_session_id": session_id,
                "title": filename,
            },
        )
        total_retries += attempts

        if err_info:
            return {"success": False, "stage": "finish", "upload_mode": "chunked",
                    "retry_count": total_retries,
                    "error": f"分片上传 finish 失败: {err_info.get('error')}",
                    "meta_response": err_info.get("body_preview", "")}

    final_video_id = data.get("video_id") or video_id
    return {"success": True, "video_id": final_video_id, "chunks": chunk_num,
            "upload_mode": "chunked", "retry_count": total_retries}


async def _poll_video_thumbnail(video_id: str, token: str, max_attempts: int = 3, delay: float = 3.0) -> str | None:
    """上传视频后轮询获取 Meta 自动生成的封面图 URL。返回 URL 或 None。"""
    import httpx
    url = f"https://graph.facebook.com/v21.0/{video_id}"
    params = {"fields": "picture,status", "access_token": token}

    async with httpx.AsyncClient(timeout=15.0) as http:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await http.get(url, params=params)
                data = resp.json()
                pic = data.get("picture")
                status = data.get("status", {})
                processing = status.get("video_status", "") if isinstance(status, dict) else ""

                if pic:
                    logger.info(f"[meta-assets] 视频封面获取成功 (attempt={attempt}): video_id={video_id}, url={pic[:80]}")
                    return pic

                logger.info(f"[meta-assets] 视频封面尚未就绪 (attempt={attempt}/{max_attempts}): "
                            f"video_id={video_id}, status={processing}")
            except Exception as e:
                logger.warning(f"[meta-assets] 获取视频封面异常 (attempt={attempt}): {e}")

            if attempt < max_attempts:
                await asyncio.sleep(delay)

    logger.warning(f"[meta-assets] 视频封面获取超时: video_id={video_id}, 已轮询 {max_attempts} 次")
    return None


@router.post("/upload-video")
async def upload_video(
    request: Request,
    ad_account_id: str = Form(...),
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
):
    """流式接收 → 临时文件 → simple/chunked + 自动降级"""
    t0 = time.time()
    filename = file.filename or "upload.mp4"
    content_type = request.headers.get("content-type", "unknown")
    logger.info(
        f"[meta-assets] 视频上传请求: account={ad_account_id}, file={filename}, "
        f"content_type={content_type[:80]}, user={_user.username}"
    )

    try:
        token = _get_token_for_account(ad_account_id)
    except Exception as e:
        logger.error(f"[meta-assets] 获取 token 失败: {e}")
        return JSONResponse(content={"success": False, "error": f"获取账户凭证失败: {e}"})

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXT:
        return JSONResponse(content={
            "success": False,
            "error": f"不支持的视频格式 {ext}，支持: {', '.join(sorted(_ALLOWED_VIDEO_EXT))}",
        })

    tmp_path = None
    try:
        from core.isolation import scoped_temp_dir
        with tempfile.NamedTemporaryFile(
            suffix=ext,
            delete=False,
            dir=scoped_temp_dir("meta-uploads"),
        ) as tmp:
            tmp_path = tmp.name
            file_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
                file_size += len(chunk)

        if file_size == 0:
            return JSONResponse(content={"success": False, "error": "接收到的文件为空（0 字节），请检查上传"})

        if file_size > _VIDEO_MAX:
            return JSONResponse(content={
                "success": False,
                "error": f"视频文件过大: {file_size / 1024 / 1024:.1f}MB，最大允许 {_VIDEO_MAX // 1024 // 1024}MB",
            })

        t_saved = time.time()
        size_mb = file_size / 1024 / 1024
        initial_mode = "simple" if file_size <= _SIMPLE_THRESHOLD else "chunked"
        logger.info(
            f"[meta-assets] 视频已保存临时文件: size={file_size} ({size_mb:.1f}MB), "
            f"save_time={int((t_saved - t0) * 1000)}ms, initial_mode={initial_mode}"
        )

        # ── 首选模式上传 ──
        if initial_mode == "simple":
            result = await _simple_upload_to_meta(
                ad_account_id, token, tmp_path, file_size, filename,
            )
        else:
            result = await _chunked_upload_to_meta(
                ad_account_id, token, tmp_path, file_size, filename,
            )

        # ── 降级：chunked start 失败 + 文件 ≤ 阈值 → 尝试 simple ──
        fallback_used = False
        if not result.get("success") and result.get("stage") == "start" and file_size <= _SIMPLE_THRESHOLD:
            logger.warning(
                f"[meta-assets] 分片 start 失败，文件 {size_mb:.1f}MB ≤ {_SIMPLE_THRESHOLD // 1024 // 1024}MB，"
                f"降级到 simple 上传"
            )
            fallback_used = True
            result = await _simple_upload_to_meta(
                ad_account_id, token, tmp_path, file_size, filename,
            )
            if result.get("success"):
                result["upload_mode"] = "chunked->simple"
                logger.info(f"[meta-assets] 降级 simple 上传成功: video_id={result.get('video_id')}")
            else:
                result["upload_mode"] = "chunked->simple"
                logger.error(f"[meta-assets] 降级 simple 上传也失败: {result.get('error')}")

        elapsed = int((time.time() - t0) * 1000)
        upload_mode = result.get("upload_mode", initial_mode)
        retry_count = result.get("retry_count", 0)

        if not result.get("success"):
            logger.error(
                f"[meta-assets] 视频上传最终失败: upload_mode={upload_mode}, "
                f"stage={result.get('stage')}, retry_count={retry_count}, "
                f"file={filename}, size={size_mb:.1f}MB, elapsed={elapsed}ms"
            )
            return JSONResponse(content={
                "success": False,
                "stage": result.get("stage", "unknown"),
                "upload_mode": upload_mode,
                "retry_count": retry_count,
                "error": result.get("error", "上传失败"),
                "meta_response": result.get("meta_response", ""),
                "size": file_size, "upload_time_ms": elapsed,
            })

        video_id = result["video_id"]
        logger.info(
            f"[meta-assets] 视频上传成功: video_id={video_id}, upload_mode={upload_mode}, "
            f"retry_count={retry_count}, chunks={result.get('chunks', 0)}, "
            f"size={size_mb:.1f}MB, elapsed={elapsed}ms, fallback={fallback_used}"
        )

        picture_url = await _poll_video_thumbnail(video_id, token)

        elapsed = int((time.time() - t0) * 1000)
        return JSONResponse(content={
            "success": True, "video_id": video_id, "name": filename,
            "upload_mode": upload_mode, "retry_count": retry_count,
            "size": file_size, "upload_time_ms": elapsed,
            "picture_url": picture_url,
        })

    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error(f"[meta-assets] 视频上传异常: type={type(e).__name__}, msg={e}, elapsed={elapsed}ms")
        return JSONResponse(content={"success": False, "stage": "exception",
                                     "upload_mode": "unknown", "error": f"上传异常: {e}"})
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
