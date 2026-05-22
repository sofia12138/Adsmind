"""阶段 3 批次 1 shim — 原内容已迁至 `plugins.designer_performance.routes`。

app.py 已不再 import 本文件；1~2 周后将删除。
新代码请直接 `from plugins.designer_performance.routes import router`。
"""
import sys
from plugins.designer_performance import routes as _impl

sys.modules[__name__] = _impl
