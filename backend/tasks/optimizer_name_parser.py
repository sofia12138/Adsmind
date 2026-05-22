"""阶段 3 批次 1 shim — 原内容已迁至 `plugins.optimizer.name_parser`。

本文件是过渡期兼容垫片，1~2 周后将删除。
新代码请直接 `from plugins.optimizer.name_parser import ...`。
"""
import sys
from plugins.optimizer import name_parser as _impl

sys.modules[__name__] = _impl
