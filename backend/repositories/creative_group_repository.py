"""Application-scoped creative groups."""
from repositories import application_resource_repository as _resources


def _validate_refs(asset_refs: list[dict]) -> None:
    if not isinstance(asset_refs, list) or any(not isinstance(ref, dict) for ref in asset_refs):
        raise ValueError("asset_refs 必须是素材引用列表")
    if not asset_refs:
        return
    from repositories import (
        asset_copy_pack_repository,
        asset_landing_page_repository,
        asset_region_group_repository,
        tiktok_material_repository,
    )
    getters = {
        "copy_pack": asset_copy_pack_repository.get_by_id,
        "landing_page": asset_landing_page_repository.get_by_id,
        "region_group": asset_region_group_repository.get_by_id,
        "tiktok_material": tiktok_material_repository.get_by_id,
    }
    for ref in asset_refs:
        kind = str(ref.get("kind") or "")
        getter = getters.get(kind)
        try:
            asset_id = int(ref.get("id"))
        except (TypeError, ValueError):
            asset_id = 0
        if not getter or asset_id <= 0:
            raise ValueError("素材引用必须包含受支持的 kind 和正整数 id")
        if getter(asset_id) is None:
            raise ValueError("素材不存在或不属于当前租户")


def create(*, name: str, asset_refs: list[dict], created_by: str = "") -> dict:
    _validate_refs(asset_refs)
    return _resources.create("creative_group", name=name, payload=asset_refs, created_by=created_by)


def get(group_id: int):
    return _resources.get("creative_group", group_id)


def list_all():
    return _resources.list_all("creative_group")


def update(group_id: int, *, name: str, asset_refs: list[dict]):
    if get(group_id) is None:
        return None
    _validate_refs(asset_refs)
    return _resources.update("creative_group", group_id, name=name, payload=asset_refs)


def delete(group_id: int) -> bool:
    return _resources.delete("creative_group", group_id)
