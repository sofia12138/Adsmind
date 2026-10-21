"""Application-scoped account groups."""
from repositories import application_resource_repository as _resources


def create(*, name: str, account_refs: list[dict], created_by: str = "") -> dict:
    return _resources.create("account_group", name=name, payload=account_refs, created_by=created_by)


def get(group_id: int):
    return _resources.get("account_group", group_id)


def list_all():
    return _resources.list_all("account_group")


def update(group_id: int, *, name: str, account_refs: list[dict]):
    return _resources.update("account_group", group_id, name=name, payload=account_refs)


def delete(group_id: int) -> bool:
    return _resources.delete("account_group", group_id)
