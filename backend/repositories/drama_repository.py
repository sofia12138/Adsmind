"""阶段 3 批次 1 shim — 原内容已迁至 `plugins.drama.repository`。

本文件是过渡期兼容垫片，所有符号均代理到新模块。1~2 周后将删除。
新代码请直接 `from plugins.drama.repository import ...`。

参见 docs/saas-transformation.md §21。
"""
import sys
from plugins.drama import repository as _impl

sys.modules[__name__] = _impl
