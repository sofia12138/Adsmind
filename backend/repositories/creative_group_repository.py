"""Application-scoped creative groups."""
from repositories import application_resource_repository as _resources


def create(*, name: str, asset_refs: list[dict], created_by: str = "") -> dict:
    return _resources.create("creative_group", name=name, payload=asset_refs, created_by=created_by)


def get(group_id: int):
    return _resources.get("creative_group", group_id)


def list_all():
    return _resources.list_all("creative_group")


def update(group_id: int, *, name: str, asset_refs: list[dict]):
    return _resources.update("creative_group", group_id, name=name, payload=asset_refs)


def delete(group_id: int) -> bool:
    return _resources.delete("creative_group", group_id)
