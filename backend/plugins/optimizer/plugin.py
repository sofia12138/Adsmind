"""optimizer 插件入口。"""
from __future__ import annotations

from core import plugin_loader
from plugins.base import Plugin, PluginMeta


class OptimizerPlugin(Plugin):
    meta = PluginMeta(
        name="optimizer",
        label="优化师人效",
        version="0.1.0",
        panels=["optimizer_performance", "optimizer_directory"],
    )

    def register_routes(self, app) -> None:
        from plugins.optimizer.routes_performance import router as perf_router
        from plugins.optimizer.routes_directory import router as dir_router

        app.include_router(perf_router, prefix="/api")
        app.include_router(dir_router, prefix="/api")


plugin_loader.register(OptimizerPlugin())
