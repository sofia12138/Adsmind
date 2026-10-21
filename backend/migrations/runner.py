"""Small explicit migration runner with ordered, checksummed history."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import hashlib
import inspect
import re
from typing import Callable

from db import get_app_conn


MODULES = (
    "migrations.versions.v0001_legacy_baseline",
    "migrations.versions.v0002_scope_foreign_keys",
    "migrations.versions.v0003_application_resources",
    # 0004 is reserved for the drama-catalog branch and must be inserted here
    # by the integrating branch before 0005 can be executed.
    "migrations.versions.v0005_application_settings_panels",
)


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    reversible: bool
    checksum: str
    upgrade: Callable[[], None]
    downgrade: Callable[[], None]


def migrations() -> list[Migration]:
    result = []
    for name in MODULES:
        module = import_module(name)
        source = inspect.getsource(module).encode("utf-8")
        result.append(Migration(
            module.VERSION,
            module.DESCRIPTION,
            module.REVERSIBLE,
            hashlib.sha256(source).hexdigest(),
            module.upgrade,
            module.downgrade,
        ))
    return result


def plan() -> list[dict]:
    """Return the complete reviewable plan without connecting to a database."""
    return [
        {
            "version": item.version,
            "description": item.description,
            "reversible": item.reversible,
            "checksum": item.checksum,
        }
        for item in migrations()
    ]


def _assert_contiguous_upgrade_sequence(items: list[Migration]) -> None:
    """Reject a real upgrade before connecting when a numbered step is absent."""
    numbers = []
    for item in items:
        match = re.match(r"^(\d{4})_", item.version)
        if not match:
            raise RuntimeError(f"迁移版本格式无效：{item.version}")
        numbers.append(int(match.group(1)))
    if not numbers:
        return
    expected = set(range(min(numbers), max(numbers) + 1))
    missing = sorted(expected - set(numbers))
    if missing:
        formatted = ", ".join(f"{number:04d}" for number in missing)
        raise RuntimeError(f"迁移序列存在缺口：缺少 {formatted}；拒绝连接数据库执行升级")


def _ensure_history() -> None:
    with get_app_conn() as conn:
        conn.cursor().execute(
            """CREATE TABLE IF NOT EXISTS app_schema_migrations (
                version VARCHAR(128) PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        conn.commit()


def applied() -> dict[str, str]:
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT version, checksum FROM app_schema_migrations ORDER BY version")
        return {row["version"]: row["checksum"] for row in (cur.fetchall() or [])}


def upgrade_all() -> list[str]:
    planned = migrations()
    _assert_contiguous_upgrade_sequence(planned)
    _ensure_history()
    existing = applied()
    completed: list[str] = []
    for migration in planned:
        previous = existing.get(migration.version)
        if previous:
            if previous != migration.checksum:
                raise RuntimeError(f"已执行迁移 {migration.version} 的校验和发生变化")
            continue
        migration.upgrade()
        with get_app_conn() as conn:
            conn.cursor().execute(
                "INSERT INTO app_schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
            conn.commit()
        completed.append(migration.version)
    return completed


def downgrade_one() -> str:
    existing = applied()
    if not existing:
        raise RuntimeError("没有可回滚的迁移")
    known = {item.version: item for item in migrations()}
    version = sorted(existing)[-1]
    migration = known.get(version)
    if not migration:
        raise RuntimeError(f"数据库包含当前代码未知的迁移：{version}")
    if not migration.reversible:
        raise RuntimeError(f"迁移 {version} 不支持自动回滚")
    migration.downgrade()
    with get_app_conn() as conn:
        conn.cursor().execute(
            "DELETE FROM app_schema_migrations WHERE version=%s", (version,)
        )
        conn.commit()
    return version
