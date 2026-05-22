"""轻量 per-IP 限流（阶段 7 P0 安全加固）。

为什么不直接用 slowapi / Redis？
  - 当前部署是单进程 uvicorn，引入 Redis 会大幅增加运维复杂度
  - 注册 / 登录 / 邀请这类敏感端点的 QPS 极低，进程内计数已足够
  - 上 Redis 时只需把 _BUCKET 换成 Redis backend，接口不变

后续扩 Redis 时迁移点：
  - `_consume()` 改成 INCR + EXPIRE 的 lua script
  - `RateLimiter` 接口保持不变

特性：
  - 滑动 / 固定窗口（这里用固定窗口足够简单，误差容忍范围内）
  - per-key（默认 client IP，可自定义 key extractor 比如 email）
  - 命中返回 429 + Retry-After
  - 路由层用 FastAPI Depends 接入：
        from core.rate_limit import limit
        @router.post("/x", dependencies=[Depends(limit("login", per_minute=10))])
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import HTTPException, Request


# ─────────────────────────────────────────────────────────────
# 后端存储
# ─────────────────────────────────────────────────────────────

@dataclass
class _Bucket:
    window_start: float
    count: int


# {(scope, key): _Bucket}
_BUCKET: dict[tuple[str, str], _Bucket] = defaultdict(
    lambda: _Bucket(window_start=time.time(), count=0)
)
_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    # 优先 X-Forwarded-For（nginx 部署典型），否则 client.host
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "unknown") or "unknown"


def _consume(scope: str, key: str, limit: int, window_sec: int) -> tuple[bool, int]:
    """尝试消耗 1 次；返回 (allowed, retry_after_sec)。"""
    now = time.time()
    bucket_key = (scope, key)
    with _LOCK:
        b = _BUCKET[bucket_key]
        if now - b.window_start >= window_sec:
            b.window_start = now
            b.count = 0
        if b.count >= limit:
            retry = max(1, int(window_sec - (now - b.window_start)))
            return False, retry
        b.count += 1
        return True, 0


# ─────────────────────────────────────────────────────────────
# 对外 API
# ─────────────────────────────────────────────────────────────

def _enabled() -> bool:
    try:
        from config import get_settings
        return bool(getattr(get_settings(), "rate_limit_enabled", True))
    except Exception:
        return True


def limit(scope: str,
          *,
          per_minute: Optional[int] = None,
          per_hour: Optional[int] = None,
          key_func: Optional[Callable[[Request], str]] = None):
    """返回 FastAPI Dependency；触发时抛 429。

    用法：
        @router.post("/login",
                     dependencies=[Depends(limit("login", per_minute=10))])
        async def login(...): ...

    `scope` 仅用于隔离不同端点的 counter，避免互相干扰；
    `key_func` 缺省取 client IP。
    """
    if per_minute is None and per_hour is None:
        raise ValueError("必须至少指定 per_minute / per_hour 中的一个")
    if per_minute is not None and per_hour is not None:
        raise ValueError("per_minute / per_hour 只能指定一个")

    if per_minute is not None:
        win = 60
        limit_n = per_minute
    else:
        win = 3600
        limit_n = per_hour  # type: ignore[assignment]

    extractor = key_func or _client_ip

    async def _dep(request: Request) -> None:
        if not _enabled():
            return
        try:
            key = extractor(request)
        except Exception:
            key = "unknown"
        ok, retry = _consume(scope, key, limit=int(limit_n), window_sec=win)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "请求过于频繁，请稍后再试",
                    "retry_after_sec": retry,
                },
                headers={"Retry-After": str(retry)},
            )

    # 给 dep 起个能在 stack trace 里识别的名字
    _dep.__name__ = f"rate_limit__{scope}"  # type: ignore[attr-defined]
    return _dep


def reset_for_tests() -> None:
    with _LOCK:
        _BUCKET.clear()
