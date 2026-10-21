"""Application-scoped account groups."""
from core.isolation import require_owned_accounts
from db import get_biz_conn
from repositories import application_resource_repository as _resources


def _validate_refs(account_refs: list[dict]) -> None:
    if not isinstance(account_refs, list) or any(not isinstance(ref, dict) for ref in account_refs):
        raise ValueError("account_refs 必须是账户引用列表")
    if not account_refs:
        return
    with get_biz_conn() as conn:
        require_owned_accounts(conn, account_refs)


def create(*, name: str, account_refs: list[dict], created_by: str = "") -> dict:
    _validate_refs(account_refs)
    return _resources.create("account_group", name=name, payload=account_refs, created_by=created_by)


def get(group_id: int):
    return _resources.get("account_group", group_id)


def list_all():
    return _resources.list_all("account_group")


def update(group_id: int, *, name: str, account_refs: list[dict]):
    if get(group_id) is None:
        return None
    _validate_refs(account_refs)
    return _resources.update("account_group", group_id, name=name, payload=account_refs)


def delete(group_id: int) -> bool:
    return _resources.delete("account_group", group_id)
