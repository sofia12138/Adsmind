"""Naming-rule validation and CRUD for the currently verified application."""
from __future__ import annotations

from string import Formatter
from fastapi import HTTPException
from pymysql.err import IntegrityError

from repositories import naming_rule_repository


ALLOWED_FIELDS = {
    "platform", "account", "product", "country", "language",
    "campaign", "adgroup", "creative", "date",
}


def _name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        raise ValueError("规则名称不能为空")
    if len(name) > 160:
        raise ValueError("规则名称不能超过 160 个字符")
    return name


def normalize_rule(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("命名规则格式无效")
    pattern = str(value.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("命名模板不能为空")
    if len(pattern) > 300:
        raise ValueError("命名模板不能超过 300 个字符")
    try:
        parsed = list(Formatter().parse(pattern))
    except ValueError as exc:
        raise ValueError("命名模板中的大括号不匹配") from exc
    if any(format_spec or conversion for _, field, format_spec, conversion in parsed if field):
        raise ValueError("命名模板不支持格式化说明或类型转换")
    fields = [field for _, field, _, _ in parsed if field]
    if not fields:
        raise ValueError("命名模板至少需要一个占位符")
    unknown = sorted(set(fields) - ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"不支持的占位符：{', '.join(unknown)}")
    description = str(value.get("description") or "").strip()
    if len(description) > 500:
        raise ValueError("规则说明不能超过 500 个字符")
    return {"pattern": pattern, "description": description, "fields": list(dict.fromkeys(fields))}


def list_rules() -> list[dict]:
    return naming_rule_repository.list_all()


def get_rule(rule_id: int) -> dict | None:
    return naming_rule_repository.get(rule_id)


def create_rule(*, name: str, rule: dict, created_by: str) -> dict:
    try:
        return naming_rule_repository.create(
            name=_name(name), rule=normalize_rule(rule), created_by=created_by
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="当前应用已存在同名命名规则") from exc


def update_rule(rule_id: int, *, name: str, rule: dict) -> dict | None:
    try:
        return naming_rule_repository.update(
            rule_id, name=_name(name), rule=normalize_rule(rule)
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="当前应用已存在同名命名规则") from exc


def delete_rule(rule_id: int) -> bool:
    return naming_rule_repository.delete(rule_id)
