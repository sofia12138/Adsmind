"""业务插件包 — 阶段 3 业务插件化（batch 1）。

每个子包对应一个可独立装卸的业务模块（drama / optimizer / attribution_metis 等），
通过 `core.plugin_loader.load_all` 在启动时统一注册。

设计准则见 docs/saas-transformation.md §21（阶段 3）。
"""
