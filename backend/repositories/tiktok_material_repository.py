"""TikTok 素材上传记录 — tiktok_material_uploads 表 CRUD"""
from __future__ import annotations

from typing import Optional

from core.isolation import tenant_cursor
from db import get_biz_conn


def create(data: dict) -> int:
    """新增一条上传记录，返回自增 id"""
    sql = """
        INSERT INTO tiktok_material_uploads
          (advertiser_id, local_file_name, file_size_bytes, duration_sec,
           upload_channel, upload_status, can_use_for_ad, ad_usage_note, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'tiktok_material_uploads')
        cur.execute(sql, (
            data["advertiser_id"],
            data.get("local_file_name", ""),
            data.get("file_size_bytes", 0),
            data.get("duration_sec"),
            data.get("upload_channel", "api"),
            data.get("upload_status", "pending"),
            data.get("can_use_for_ad", 0),
            data.get("ad_usage_note", ""),
            data.get("created_by", ""),
        ))
        conn.commit()
        return cur.lastrowid


def update_status(record_id: int, status: str, **kwargs) -> int:
    """更新上传状态及相关字段"""
    fields = ["upload_status = %s"]
    params: list = [status]

    for col in (
        "tiktok_video_id", "tiktok_file_name", "tiktok_url",
        "tiktok_width", "tiktok_height", "tiktok_format",
        "duration_sec",
        "error_code", "error_message",
        "can_use_for_ad", "ad_usage_note",
    ):
        if col in kwargs:
            fields.append(f"{col} = %s")
            params.append(kwargs[col])

    params.append(record_id)
    sql = f"UPDATE tiktok_material_uploads SET {', '.join(fields)} WHERE id = %s"

    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'tiktok_material_uploads')
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount


def get_by_id(record_id: int) -> Optional[dict]:
    sql = "SELECT * FROM tiktok_material_uploads WHERE id = %s"
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'tiktok_material_uploads')
        cur.execute(sql, (record_id,))
        return cur.fetchone()


def delete_by_id(record_id: int) -> int:
    sql = "DELETE FROM tiktok_material_uploads WHERE id = %s"
    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'tiktok_material_uploads')
        cur.execute(sql, (record_id,))
        conn.commit()
        return cur.rowcount


def list_all(
    *,
    advertiser_id: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """分页查询上传记录，返回 (rows, total)"""
    clauses = ["1=1"]
    params: list = []

    if advertiser_id:
        clauses.append("advertiser_id = %s")
        params.append(advertiser_id)
    if status:
        clauses.append("upload_status = %s")
        params.append(status)
    if keyword:
        clauses.append("(local_file_name LIKE %s OR tiktok_video_id LIKE %s)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])

    where = " AND ".join(clauses)

    with get_biz_conn() as conn:
        cur = tenant_cursor(conn, 'tiktok_material_uploads')
        cur.execute(f"SELECT COUNT(*) AS cnt FROM tiktok_material_uploads WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT * FROM tiktok_material_uploads WHERE {where} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

    return rows, total
