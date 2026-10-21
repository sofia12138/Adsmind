"""Compatibility facade for the 0007 material-backed creative-group domain.

New code should import :mod:`creative_groups.service` directly. Keeping this
module prevents older internal imports from bypassing the material contract.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from creative_groups import service


def _input(name: str, asset_refs: list[dict]) -> service.CreativeGroupInput:
    try:
        return service.CreativeGroupInput(name=name, materials=asset_refs)
    except ValidationError as exc:
        raise ValueError(
            "素材引用必须使用 material_id、selection_mode 和 selected_version_id 契约"
        ) from exc


def _validate_refs(asset_refs: list[dict]) -> None:
    service.validate_materials(_input("兼容校验", asset_refs))


def create(*, name: str, asset_refs: list[dict], created_by: str = "") -> dict:
    return service.create_group(_input(name, asset_refs), created_by)


def get(group_id: int):
    try:
        return service.get_group(group_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def list_all():
    return service.list_groups()


def update(group_id: int, *, name: str, asset_refs: list[dict]):
    try:
        return service.update_group(group_id, _input(name, asset_refs))
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def delete(group_id: int) -> bool:
    if get(group_id) is None:
        return False
    service.delete_group(group_id)
    return True
