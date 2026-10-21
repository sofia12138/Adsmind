"""素材管理（视频、图片、视频上传）"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
from loguru import logger

from tiktok_ads.api.client import TikTokClient, TikTokApiError
from core.isolation import default_account_id
from config import get_settings


from typing import Callable


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_DEFAULT_READ_CHUNK = 4 * 1024 * 1024  # 4MB


class _ProgressReader:
    """包装文件对象，每次 read 时回调已发送字节数。

    httpx 的 multipart 在底层多次调用 read(-1)，将其映射为固定 4MB，
    可显著降低单次 syscall 大小、减少回调抖动，并提升网络写入吞吐。
    """

    def __init__(self, fp, total: int, callback: Callable[[int, int], None]):
        self._fp = fp
        self._total = total
        self._sent = 0
        self._cb = callback

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = _DEFAULT_READ_CHUNK
        data = self._fp.read(size)
        if data:
            self._sent += len(data)
            self._cb(self._sent, self._total)
        return data


_UPLOAD_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=30.0)


class CreativeService:
    def __init__(self, client: TikTokClient | None = None,
                 advertiser_id: str | None = None):
        self.advertiser_id = advertiser_id or default_account_id("tiktok")
        self.client = client or TikTokClient(account_id=self.advertiser_id or None)

    async def list_videos(self, page: int = 1, page_size: int = 20) -> dict:
        params = {
            "advertiser_id": self.advertiser_id,
            "filtering": json.dumps({}),
            "page": page,
            "page_size": page_size,
        }
        return await self.client.get("file/video/ad/search/", params)

    async def get_video_info(self, video_ids: list[str]) -> dict:
        params = {
            "advertiser_id": self.advertiser_id,
            "video_ids": json.dumps(video_ids),
        }
        return await self.client.get("file/video/ad/info/", params)

    async def list_images(self, page: int = 1, page_size: int = 20) -> dict:
        params = {
            "advertiser_id": self.advertiser_id,
            "filtering": json.dumps({}),
            "page": page,
            "page_size": page_size,
        }
        return await self.client.get("file/image/ad/search/", params)

    async def upload_image_by_url(self, image_url: str, file_name: str) -> dict:
        payload = {
            "advertiser_id": self.advertiser_id,
            "upload_type": "UPLOAD_BY_URL",
            "image_url": image_url,
            "file_name": file_name,
        }
        return await self.client.post("file/image/ad/upload/", payload)

    async def list_apps(self) -> dict:
        params = {"advertiser_id": self.advertiser_id}
        return await self.client.get("app/list/", params)

    async def list_identities(self, identity_type: str = "BC_AUTH_TT") -> dict:
        params = {
            "advertiser_id": self.advertiser_id,
            "identity_type": identity_type,
        }
        return await self.client.get("identity/get/", params)

    # ── TikTok 视频上传 (multipart file_upload) ─────────────

    async def upload_video_by_file(
        self,
        file_path: str,
        file_name: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        file_md5: str | None = None,
    ) -> dict:
        """通过本地文件上传视频到 TikTok Asset Library。
        TikTok API: POST file/video/ad/upload/
        必填字段: advertiser_id, upload_type=UPLOAD_BY_FILE, video_file, video_signature(MD5)
        on_progress(sent_bytes, total_bytes) 在每次网络写入时回调。
        file_md5 若由调用方在接收阶段同步算出，则跳过本地重复扫描。
        返回 {'video_id': '...', ...}
        """
        url = f"{self.client.base_url}/file/video/ad/upload/"
        fname = file_name or Path(file_path).name
        file_size = Path(file_path).stat().st_size

        if file_md5:
            video_sig = file_md5
            logger.info(f"[tiktok-upload] 使用预计算 MD5: {video_sig}")
        else:
            video_sig = _file_md5(file_path)

        logger.info(
            f"[tiktok-upload] 开始上传视频: advertiser={self.advertiser_id}, "
            f"file={fname}, size={file_size / 1024 / 1024:.1f}MB, "
            f"md5={video_sig}, upload_type=UPLOAD_BY_FILE, url={url}"
        )

        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as http:
            logger.info(
                f"[tiktok-upload] AsyncClient 已创建 (httpx={httpx.__version__}, "
                f"timeout=read:{_UPLOAD_TIMEOUT.read}s), 即将发送 multipart/form-data"
            )
            with open(file_path, "rb") as f:
                file_obj = _ProgressReader(f, file_size, on_progress) if on_progress else f
                resp = await http.post(
                    url,
                    headers={"Access-Token": self.client.access_token},
                    data={
                        "advertiser_id": self.advertiser_id,
                        "upload_type": "UPLOAD_BY_FILE",
                        "video_signature": video_sig,
                        "file_name": fname,
                    },
                    files={"video_file": (fname, file_obj, "video/mp4")},
                )

        logger.info(
            f"[tiktok-upload] TikTok 响应: status={resp.status_code}, "
            f"content-type={resp.headers.get('content-type')}, len={len(resp.content)}"
        )
        resp.raise_for_status()
        body = resp.json()
        logger.debug(f"[tiktok-upload] 响应体: {json.dumps(body, ensure_ascii=False)[:500]}")
        if body.get("code") != 0:
            logger.error(
                f"[tiktok-upload] API 返回错误: code={body.get('code')}, "
                f"msg={body.get('message')}, request_id={body.get('request_id')}, "
                f"advertiser={self.advertiser_id}, file={fname}, upload_type=UPLOAD_BY_FILE"
            )
            raise TikTokApiError(
                code=body.get("code", -1),
                message=body.get("message", "Unknown upload error"),
                request_id=body.get("request_id", ""),
            )
        raw_data = body.get("data", {})
        # TikTok upload API 返回 data 可能是 list（如 [{"video_id": "..."}]）或 dict
        if isinstance(raw_data, list):
            data = raw_data[0] if raw_data else {}
        else:
            data = raw_data if isinstance(raw_data, dict) else {}
        logger.info(
            f"[tiktok-upload] 上传成功: video_id={data.get('video_id')}, "
            f"advertiser={self.advertiser_id}, file={fname}, "
            f"raw_data_type={type(raw_data).__name__}, raw_data_len={len(raw_data) if isinstance(raw_data, list) else 'N/A'}"
        )
        return data

    async def upload_video_by_url(self, video_url: str, file_name: str | None = None) -> dict:
        """通过 URL 上传视频到 TikTok Asset Library（无需本地文件）。
        TikTok API: POST file/video/ad/upload/
        """
        payload = {
            "advertiser_id": self.advertiser_id,
            "upload_type": "UPLOAD_BY_URL",
            "video_url": video_url,
        }
        if file_name:
            payload["file_name"] = file_name

        logger.info(f"[tiktok-upload] URL 上传: advertiser={self.advertiser_id}, url={video_url[:80]}")
        return await self.client.post("file/video/ad/upload/", payload)

    async def get_video_info_detail(self, video_ids: list[str]) -> list[dict]:
        """获取视频详细信息（含时长/分辨率等）。
        TikTok API: GET file/video/ad/info/
        """
        params = {
            "advertiser_id": self.advertiser_id,
            "video_ids": json.dumps(video_ids),
        }
        data = await self.client.get("file/video/ad/info/", params)
        return data.get("list", [])

    async def search_videos(
        self, *, page: int = 1, page_size: int = 20,
        video_ids: list[str] | None = None,
    ) -> dict:
        """搜索 TikTok Asset Library 中的视频。
        TikTok API: GET file/video/ad/search/
        """
        filtering: dict = {}
        if video_ids:
            filtering["video_ids"] = video_ids
        params = {
            "advertiser_id": self.advertiser_id,
            "filtering": json.dumps(filtering),
            "page": page,
            "page_size": page_size,
        }
        return await self.client.get("file/video/ad/search/", params)
