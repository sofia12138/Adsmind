"""optimizer 插件 — 优化师人效分析 + 名单配置。

代码搬迁前位置：
- routes_performance.py     ← backend/routes/optimizer_performance.py
- routes_directory.py       ← backend/routes/optimizer_directory.py
- repository_performance.py ← backend/repositories/optimizer_performance_repository.py
- repository_directory.py   ← backend/repositories/optimizer_directory_repository.py
- sync_job.py               ← backend/tasks/sync_optimizer.py
- name_parser.py            ← backend/tasks/optimizer_name_parser.py

原路径保留 shim，过渡期 1~2 周后清理。
"""
