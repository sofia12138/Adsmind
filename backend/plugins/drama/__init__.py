"""drama 插件 — 短剧出海业务分析（剧级总览/语言版本/趋势 + 解析与同步）。

代码搬迁前位置：
- routes.py        ← backend/routes/drama.py
- repository.py    ← backend/repositories/drama_repository.py
- sync_job.py      ← backend/tasks/sync_drama.py
- name_parser.py   ← backend/tasks/drama_name_parser.py

原路径保留 shim，过渡期 1~2 周后清理。
"""
