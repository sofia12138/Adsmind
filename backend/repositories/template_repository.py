"""模板数据访问层 — 封装 app_templates 表的所有 SQL 操作"""
from __future__ import annotations

import json
from typing import Optional

from core.isolation import tenant_cursor
from db import get_app_conn
from services.delivery_language import (
    DEFAULT_DELIVERY_LANGUAGE,
    DEFAULT_DELIVERY_LANGUAGES,
)


def _row_to_dict(row: dict) -> dict:
    """将 DB 行转换为与旧 JSON 兼容的模板字典"""
    content = row.get("content", {})
    if isinstance(content, str):
        content = json.loads(content)
    result = {
        "id": row["tpl_id"],
        "name": row["name"],
        "platform": row["platform"],
        "is_builtin": bool(row.get("is_builtin", 0)),
        "is_system": bool(row.get("is_system", 0)),
        "is_editable": bool(row.get("is_editable", 1)),
        "template_key": row.get("template_key") or None,
        "parent_template_id": row.get("parent_template_id") or None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
    # content 中允许包含模板特有字段；不要让它覆盖上面这些"行级"字段
    reserved = {"id", "name", "platform", "is_builtin", "is_system",
                "is_editable", "template_key", "parent_template_id",
                "created_at", "updated_at"}
    for k, v in content.items():
        if k not in reserved:
            result[k] = v
    # 兜底：旧记录没有 delivery_languages / default_delivery_language 时给默认值
    langs = result.get("delivery_languages")
    if not isinstance(langs, list) or not langs:
        result["delivery_languages"] = list(DEFAULT_DELIVERY_LANGUAGES)
    default_lang = result.get("default_delivery_language")
    if not isinstance(default_lang, str) or default_lang not in result["delivery_languages"]:
        result["default_delivery_language"] = (
            result["delivery_languages"][0] if result["delivery_languages"] else DEFAULT_DELIVERY_LANGUAGE
        )
    return result


def list_all() -> list[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        cur.execute("SELECT * FROM app_templates ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_by_tpl_id(tpl_id: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        cur.execute("SELECT * FROM app_templates WHERE tpl_id = %s", (tpl_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_by_key(template_key: str) -> Optional[dict]:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        cur.execute("SELECT * FROM app_templates WHERE template_key = %s LIMIT 1", (template_key,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create(*, tpl_id: str, name: str, platform: str,
           content: dict, is_builtin: bool = False,
           is_system: bool = False, is_editable: bool = True,
           template_key: Optional[str] = None,
           parent_template_id: Optional[str] = None,
           created_by: str = "", created_at: str | None = None) -> dict:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        sql = """INSERT INTO app_templates
                    (tpl_id, template_key, name, platform,
                     is_builtin, is_system, is_editable, parent_template_id,
                     content, created_by, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        cur.execute(sql, (
            tpl_id, template_key, name, platform,
            int(is_builtin), int(is_system), int(is_editable), parent_template_id,
            json.dumps(content, ensure_ascii=False),
            created_by,
            created_at or None,
        ))
        conn.commit()
    return get_by_tpl_id(tpl_id)  # type: ignore


def update(tpl_id: str, *, name: str | None = None,
           platform: str | None = None, content: dict | None = None) -> Optional[dict]:
    set_parts = []
    values = []
    if name is not None:
        set_parts.append("name = %s")
        values.append(name)
    if platform is not None:
        set_parts.append("platform = %s")
        values.append(platform)
    if content is not None:
        set_parts.append("content = %s")
        values.append(json.dumps(content, ensure_ascii=False))
    if not set_parts:
        return get_by_tpl_id(tpl_id)
    values.append(tpl_id)
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        cur.execute(
            f"UPDATE app_templates SET {', '.join(set_parts)} WHERE tpl_id = %s",
            values,
        )
        conn.commit()
    return get_by_tpl_id(tpl_id)


def delete(tpl_id: str) -> bool:
    with get_app_conn() as conn:
        cur = tenant_cursor(conn, 'app_templates')
        cur.execute("DELETE FROM app_templates WHERE tpl_id = %s", (tpl_id,))
        conn.commit()
        return cur.rowcount > 0
