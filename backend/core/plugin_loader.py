"""插件加载器（阶段 3 批次 1）。

调用顺序（由 backend/app.py 协调）：
  1. `register_routes(app)`  在 app 创建后立即同步调用，把可用插件的 routes 挂上去。
  2. `register_jobs_and_hooks(scheduler, settings)`  在 FastAPI lifespan startup 内调用，
      此时 scheduler 已存在。

不可用（缺依赖）的插件会被跳过并记录日志，不阻断启动。
单个插件异常被捕获，不影响其它插件。

参考 docs/saas-transformation.md §21.1。
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Optional

from loguru import logger

from plugins.base import HookHub, Plugin

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fastapi import FastAPI

# ── 注册表 ────────────────────────────────────────────────

_REGISTRY: dict[str, Plugin] = {}
_HOOK_HUB = HookHub()
_PLUGIN_MODULES_LOADED = False

# 内置插件模块路径。每个模块 import 时应调用 `plugin_loader.register(MyPlugin())`。
# 顺序无关，但保持与 app_tenants.enabled_plugins 默认值对齐便于排查。
_BUILTIN_MODULES: list[str] = [
    "plugins.drama.plugin",
    "plugins.optimizer.plugin",
    "plugins.designer_performance.plugin",
]


def register(plugin: Plugin) -> None:
    """供插件模块在 import 期间调用，登记自身。"""
    name = plugin.meta.name
    if name in _REGISTRY:
        logger.warning(f"插件 {name} 重复注册，已跳过后注册的实例")
        return
    _REGISTRY[name] = plugin


def get(name: str) -> Optional[Plugin]:
    return _REGISTRY.get(name)


def all_plugins() -> list[Plugin]:
    return list(_REGISTRY.values())


def hook_hub() -> HookHub:
    return _HOOK_HUB


# ── 加载主入口 ─────────────────────────────────────────────

def _ensure_modules_loaded() -> None:
    """幂等地 import 所有内置插件模块（触发其内部 register()）。"""
    global _PLUGIN_MODULES_LOADED
    if _PLUGIN_MODULES_LOADED:
        return
    for module_path in _BUILTIN_MODULES:
        try:
            importlib.import_module(module_path)
        except Exception as e:
            logger.error(f"插件模块加载失败 {module_path}: {e}")
    _PLUGIN_MODULES_LOADED = True


def register_routes(app: "FastAPI", settings=None) -> dict[str, str]:
    """在 app 实例创建后立即调用，注册所有可用插件的 routes。

    返回 {plugin_name: status} 摘要，便于 /health 或日志使用。
    """
    if settings is None:
        from config import get_settings
        settings = get_settings()

    _ensure_modules_loaded()

    summary: dict[str, str] = {}
    for plugin in all_plugins():
        try:
            if not plugin.is_available(settings):
                logger.info(f"插件 {plugin.meta.name} 缺少依赖 {plugin.meta.requires_env}，跳过加载")
                summary[plugin.meta.name] = "skipped"
                continue
            plugin.register_routes(app)
            logger.info(f"✓ 插件 {plugin.meta.name} 路由已注册")
            summary[plugin.meta.name] = "routes_ok"
        except Exception as e:
            logger.error(f"插件 {plugin.meta.name} 注册路由失败: {e}")
            summary[plugin.meta.name] = f"error: {e}"
    return summary


def register_jobs_and_hooks(scheduler: "AsyncIOScheduler", settings) -> dict[str, str]:
    """在 lifespan startup 内调用，注册调度任务和事件订阅。"""
    _ensure_modules_loaded()

    summary: dict[str, str] = {}
    for plugin in all_plugins():
        if not plugin.is_available(settings):
            summary[plugin.meta.name] = "skipped"
            continue
        try:
            plugin.register_jobs(scheduler, settings)
            plugin.register_hooks(_HOOK_HUB)
            summary[plugin.meta.name] = "jobs_ok"
        except Exception as e:
            logger.error(f"插件 {plugin.meta.name} 注册 jobs/hooks 失败: {e}")
            summary[plugin.meta.name] = f"error: {e}"
    return summary


def loaded_plugin_names() -> list[str]:
    """返回所有已注册且可用的插件名列表。"""
    return [p.meta.name for p in all_plugins()]
