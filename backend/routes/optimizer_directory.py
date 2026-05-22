"""阶段 3 批次 1 shim — 原内容已迁至 `plugins.optimizer.routes_directory`。

app.py 已不再 import 本文件；1~2 周后将删除。
新代码请直接 `from plugins.optimizer.routes_directory import router`。
"""
import sys
from plugins.optimizer import routes_directory as _impl

sys.modules[__name__] = _impl
