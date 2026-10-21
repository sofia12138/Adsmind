"""Creative-group validation and application-material contract."""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from pymysql.err import IntegrityError

from . import repository


class MaterialSelection(BaseModel):
    material_id: int = Field(gt=0)
    selection_mode: Literal["latest", "pinned"] = "latest"
    selected_version_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selection_mode == "pinned" and self.selected_version_id is None:
            raise ValueError("固定版本模式必须选择版本")
        if self.selection_mode == "latest" and self.selected_version_id is not None:
            raise ValueError("跟随最新版本时不能指定版本")
        return self


class CreativeGroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    materials: list[MaterialSelection] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        clean = " ".join(value.strip().split())
        if not clean:
            raise ValueError("创意组名称不能为空")
        return clean

    @model_validator(mode="after")
    def unique_materials(self):
        ids = [item.material_id for item in self.materials]
        if len(ids) != len(set(ids)):
            raise ValueError("同一素材不能在创意组中重复")
        return self


def validate_materials(data: CreativeGroupInput) -> list[dict]:
    result = []
    for item in data.materials:
        if not repository.get_selectable_material(item.material_id, item.selected_version_id):
            # Hide whether the id belongs to another tenant/application.
            raise HTTPException(404, "素材或版本不存在于当前应用")
        result.append(item.model_dump())
    return result


def list_groups() -> list[dict]:
    return repository.list_all()


def get_group(group_id: int) -> dict:
    row = repository.get(group_id)
    if not row:
        raise HTTPException(404, "创意组不存在")
    return row


def create_group(data: CreativeGroupInput, username: str) -> dict:
    try:
        return repository.create(data.name, validate_materials(data), username)
    except IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            raise HTTPException(409, "当前应用已存在同名创意组") from exc
        raise


def update_group(group_id: int, data: CreativeGroupInput) -> dict:
    if not repository.get(group_id):
        raise HTTPException(404, "创意组不存在")
    try:
        row = repository.update(group_id, data.name, validate_materials(data))
    except IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            raise HTTPException(409, "当前应用已存在同名创意组") from exc
        raise
    if not row:
        raise HTTPException(404, "创意组不存在")
    return row


def delete_group(group_id: int) -> None:
    if not repository.delete(group_id):
        raise HTTPException(404, "创意组不存在")
