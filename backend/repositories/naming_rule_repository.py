"""Application-scoped naming rules."""
from repositories import application_resource_repository as _resources


def create(*, name: str, rule: dict, created_by: str = "") -> dict:
    return _resources.create("naming_rule", name=name, payload=rule, created_by=created_by)


def get(rule_id: int):
    return _resources.get("naming_rule", rule_id)


def list_all():
    return _resources.list_all("naming_rule")


def update(rule_id: int, *, name: str, rule: dict):
    return _resources.update("naming_rule", rule_id, name=name, payload=rule)


def delete(rule_id: int) -> bool:
    return _resources.delete("naming_rule", rule_id)
