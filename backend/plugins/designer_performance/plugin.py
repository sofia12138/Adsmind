"""designer_performance 插件入口。"""
from __future__ import annotations

from core import plugin_loader
from plugins.base import Plugin, PluginMeta


class DesignerPerformancePlugin(Plugin):
    meta = PluginMeta(
        name="designer_performance",
        label="设计师人效",
        version="0.1.0",
        panels=["designer_performance"],
    )

    def register_routes(self, app) -> None:
        from plugins.designer_performance.routes import router

        app.include_router(router, prefix="/api")


plugin_loader.register(DesignerPerformancePlugin())
