"""同步任务状态管理（进程内内存存储）

支持多模块独立跟踪：
  structure  — Campaign / Adset / Ad 结构列表（名称、状态、预算）
  reports    — 各层级日报（花费 / 展示 / 点击 / 安装）
  returned   — 广告回传转化口径数据

每个模块均记录 is_running / last_synced_at / last_error / last_range。
所有状态均为进程内存，重启后重置；持久化可接入 DB 或 Redis。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# 合法模块名
MODULES = ("structure", "reports", "returned")

def _empty_state():
    return {
    m: {
        "is_running":     False,
        "last_synced_at": None,   # datetime | None
        "last_error":     None,   # str | None
        "last_range":     None,   # str，如 "2026-04-12 ~ 2026-04-13"
    }
    for m in MODULES
    }


_states: dict[tuple[int, int], dict] = {}

def _state_for_scope():
    from core.isolation import require_scope
    scope = require_scope(application=True)
    return _states.setdefault((scope.tenant_id, scope.application_id), _empty_state())


# 全局"是否有任何模块正在运行"的快捷属性
def is_any_running() -> bool:
    return any(_state_for_scope()[m]["is_running"] for m in MODULES)


# ── 单模块操作 ─────────────────────────────────────────────

def set_running(module: str, running: bool, date_range: Optional[str] = None):
    if module not in _state_for_scope():
        return
    _state_for_scope()[module]["is_running"] = running
    if date_range:
        _state_for_scope()[module]["last_range"] = date_range


def set_done(module: str, dt: Optional[datetime] = None):
    if module not in _state_for_scope():
        return
    _state_for_scope()[module]["is_running"]    = False
    _state_for_scope()[module]["last_synced_at"] = dt or datetime.now()
    _state_for_scope()[module]["last_error"]    = None


def set_error(module: str, err: str):
    if module not in _state_for_scope():
        return
    _state_for_scope()[module]["is_running"] = False
    _state_for_scope()[module]["last_error"] = err


# ── 全量状态读取 ───────────────────────────────────────────

def get_module_state(module: str) -> dict:
    """返回单个模块的可序列化状态快照"""
    if module not in _state_for_scope():
        return {}
    s = _state_for_scope()[module]
    return {
        "is_running":    s["is_running"],
        "last_synced_at": s["last_synced_at"].isoformat() if s["last_synced_at"] else None,
        "last_error":    s["last_error"],
        "last_range":    s["last_range"],
    }


def get_all_state() -> dict:
    """返回所有模块的状态快照，供 /api/sync/status 使用"""
    return {m: get_module_state(m) for m in MODULES}


# ── 向后兼容：旧代码用 get_state() 读单模块综合状态 ─────────

def get_state() -> dict:
    """
    向后兼容接口：返回 'returned' 模块状态（旧 SyncBar 依赖此方法）。
    新代码请直接使用 get_module_state() 或 get_all_state()。
    """
    return get_module_state("returned")
