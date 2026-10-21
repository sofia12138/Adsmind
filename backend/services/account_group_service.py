"""Account-group business rules for the currently verified application."""
from __future__ import annotations

from fastapi import HTTPException
from pymysql.err import IntegrityError

from repositories import account_group_repository, biz_account_repository


SUPPORTED_PLATFORMS = {"tiktok", "meta"}


def _name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        raise ValueError("账户组名称不能为空")
    if len(name) > 160:
        raise ValueError("账户组名称不能超过 160 个字符")
    return name


def _account_refs(value: list[dict]) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("账户组至少需要包含一个广告账户")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("广告账户引用格式无效")
        platform = str(item.get("platform") or "").strip().lower()
        account_id = str(item.get("account_id") or "").strip()
        if platform not in SUPPORTED_PLATFORMS or not account_id:
            raise ValueError("广告账户引用必须包含有效的 platform 和 account_id")
        key = (platform, account_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"platform": platform, "account_id": account_id})

    owned = {
        (str(row.get("platform") or "").lower(), str(row.get("account_id") or ""))
        for row in biz_account_repository.list_all()
    }
    if any((ref["platform"], ref["account_id"]) not in owned for ref in normalized):
        # Do not reveal whether a reference belongs to another application.
        raise HTTPException(status_code=404, detail="广告账户不存在")
    return normalized


def list_groups() -> list[dict]:
    return account_group_repository.list_all()


def get_group(group_id: int) -> dict | None:
    return account_group_repository.get(group_id)


def create_group(*, name: str, account_refs: list[dict], created_by: str) -> dict:
    try:
        return account_group_repository.create(
            name=_name(name),
            account_refs=_account_refs(account_refs),
            created_by=created_by,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="当前应用已存在同名账户组") from exc


def update_group(group_id: int, *, name: str, account_refs: list[dict]) -> dict | None:
    try:
        return account_group_repository.update(
            group_id,
            name=_name(name),
            account_refs=_account_refs(account_refs),
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="当前应用已存在同名账户组") from exc


def delete_group(group_id: int) -> bool:
    return account_group_repository.delete(group_id)
