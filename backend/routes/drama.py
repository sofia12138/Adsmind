"""阶段 3 批次 1 shim — 原内容已迁至 `plugins.drama.routes`。

注：app.py 已不再 import 本文件；仅保留供其它脚本兼容。
1~2 周后将删除。新代码请直接 `from plugins.drama.routes import router`。
"""
import sys
from plugins.drama import routes as _impl

sys.modules[__name__] = _impl
