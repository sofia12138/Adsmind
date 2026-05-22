"""drama 插件入口 — 仅做注册，不放业务逻辑。"""
from __future__ import annotations

from core import plugin_loader
from plugins.base import Plugin, PluginMeta


class DramaPlugin(Plugin):
    meta = PluginMeta(
        name="drama",
        label="短剧分析",
        version="0.1.0",
        panels=["drama_analysis"],
    )

    def register_routes(self, app) -> None:
        from plugins.drama.routes import router

        app.include_router(router, prefix="/api")


plugin_loader.register(DramaPlugin())
