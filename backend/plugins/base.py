"""插件基类与轻量事件总线（阶段 3 批次 1）。

约束：
- 单个 Plugin 实例代表一个业务模块，由 `core.plugin_loader` 统一调度。
- HookHub 在本批次仅提供骨架：subscribe / emit 已可用；
  实际 emit 调用点（如 sync_campaigns.after_*）由批次 3 接入。
- Plugin 的 register_routes / register_jobs / register_hooks 默认空实现，
  子类按需覆盖；这样每个插件只关心自己负责的注册点。

参考 docs/saas-transformation.md §21.1。
"""
from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass
class PluginMeta:
    """插件静态元信息。

    name 与 `app_tenants.enabled_plugins` 中的 key 严格一致。
    panels 关联前端 menuConfig 中的 panelKey 集合，用于 hasPlugin() 联动菜单可见性。
    requires_env / requires_db 为启动期硬依赖：缺失则该插件不会被 register。
    """

    name: str
    label: str = ""
    version: str = "0.1.0"
    panels: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    requires_db: list[str] = field(default_factory=list)


class Plugin(ABC):
    """业务插件基类。

    子类必须设置 `meta` 类属性（或实例属性）；其余三个 register_* 按需覆盖。
    任何方法抛出异常都会被 plugin_loader 捕获并记录，不影响主流程或其它插件。
    """

    meta: PluginMeta

    def is_available(self, settings) -> bool:
        """启动期硬依赖检查。默认 True；子类可覆盖以检查环境变量、库连接等。"""
        for key in self.meta.requires_env:
            if not getattr(settings, key, None):
                return False
        return True

    def register_routes(self, app: "FastAPI") -> None:  # noqa: B027
        """在 app 创建后立即被调用。子类用 `app.include_router(router, prefix='/api')`。"""

    def register_jobs(self, scheduler: "AsyncIOScheduler", settings) -> None:  # noqa: B027
        """在 lifespan startup 中调用。子类可向 scheduler 添加 cron/interval job。"""

    def register_hooks(self, hub: "HookHub") -> None:  # noqa: B027
        """在 lifespan startup 中调用。子类可通过 hub.subscribe 订阅事件。"""


class HookHub:
    """轻量级事件总线，用于跨插件解耦。

    用法（订阅端）：
        hub.subscribe("after_tiktok_ad_report", lambda **kw: ...)

    用法（发布端，目前预留给批次 3 的 sync_campaigns 改造）：
        plugin_loader.hook_hub().emit("after_tiktok_ad_report", advertiser_id=..., rows=...)

    单个 handler 异常被吞掉，不影响其它 handler 或调用方。
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(self, event: str, handler: Callable[..., Any]) -> None:
        self._listeners.setdefault(event, []).append(handler)

    def emit(self, event: str, **kwargs) -> None:
        for handler in self._listeners.get(event, []):
            try:
                handler(**kwargs)
            except Exception as e:
                logger.warning(f"hook handler {event}/{handler.__name__} 抛错（已吞掉）: {e}")

    def has_listeners(self, event: str) -> bool:
        return bool(self._listeners.get(event))
