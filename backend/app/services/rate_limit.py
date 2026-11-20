"""轻量滑动窗口限流。

设计取舍：
- 不引入 flask-limiter 等第三方依赖，保持后端依赖面不变；
- 进程内实现，单实例部署够用；多实例场景应由 Nginx 或云侧 WAF 承担，
  这里只作为"公网裸奔"的最低兜底；
- 默认关闭（RATE_LIMIT_ENABLED=false），避免本地开发与 CI 被误伤，
  部署模板中默认开启。
"""

import re
import threading
import time
from collections import deque

from ..config import (
    RATE_LIMIT_AGENT_TUTOR,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_MAX_KEYS,
)

WINDOW_SECONDS = 60

# (路径正则, 桶名, 每分钟上限)；按顺序匹配，先命中先生效。
POLICIES = (
    (re.compile(r"^/api/agent/ocr-tutor$"), "agent_tutor", RATE_LIMIT_AGENT_TUTOR),
    (re.compile(r"^/api/agent/(eval|eval-ab)$"), "agent_eval", 20),
    (re.compile(r"^/api/agent/kb/ingest$"), "kb_ingest", 30),
    (re.compile(r"^/api/auth/(login|register)$"), "auth", 10),
    (re.compile(r"^/api/space"), "space", 120),
    (re.compile(r"^/api/"), "api", 240),
)

EXEMPT_PATHS = frozenset({"/health", "/metrics"})


class SlidingWindowLimiter:
    """按 key 维护时间戳队列，超限即拒绝并给出建议重试时间。"""

    def __init__(self, limit, window_seconds=WINDOW_SECONDS, max_keys=None):
        self._limit = max(1, int(limit))
        self._window = max(1.0, float(window_seconds))
        self._max_keys = max(64, int(max_keys or RATE_LIMIT_MAX_KEYS))
        self._lock = threading.Lock()
        self._buckets = {}
        self._allowed = 0
        self._rejected = 0

    def hit(self, key):
        """返回 (是否放行, 建议等待秒数)。"""
        now = time.monotonic()
        with self._lock:
            queue = self._buckets.get(key)
            if queue is None:
                if len(self._buckets) >= self._max_keys:
                    self._evict_locked(now)
                queue = deque()
                self._buckets[key] = queue

            cutoff = now - self._window
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= self._limit:
                self._rejected += 1
                return False, max(0.0, queue[0] + self._window - now)

            queue.append(now)
            self._allowed += 1
            return True, 0.0

    def _evict_locked(self, now):
        """先清理已过期的 key，仍然超限时淘汰最久未活动的 10%。"""
        cutoff = now - self._window
        for key in [k for k, q in self._buckets.items() if not q or q[-1] <= cutoff]:
            self._buckets.pop(key, None)

        if len(self._buckets) >= self._max_keys:
            ordered = sorted(
                self._buckets.items(),
                key=lambda item: item[1][-1] if item[1] else 0.0,
            )
            for key, _ in ordered[: max(1, self._max_keys // 10)]:
                self._buckets.pop(key, None)

    def snapshot(self):
        with self._lock:
            return {
                "limit_per_minute": self._limit,
                "tracked_keys": len(self._buckets),
                "allowed": self._allowed,
                "rejected": self._rejected,
            }


_limiters = {}
_limiters_lock = threading.Lock()


def _get_limiter(name, limit):
    with _limiters_lock:
        limiter = _limiters.get(name)
        if limiter is None:
            limiter = SlidingWindowLimiter(limit)
            _limiters[name] = limiter
        return limiter


def resolve_policy(path):
    """返回 (桶名, 每分钟上限)，未命中返回 None。"""
    if not path or path in EXEMPT_PATHS:
        return None
    for pattern, name, limit in POLICIES:
        if pattern.search(path):
            return name, limit
    return None


def resolve_client_key():
    """在反向代理后取真实客户端 IP。

    Nginx 用 proxy_set_header 覆盖 X-Real-IP，经本机/内网代理转发时该头可信；
    直连公网时客户端虽可伪造它，但那只影响自己的配额，不构成越权。
    """
    from flask import request

    remote = (request.remote_addr or "").strip()
    is_proxied = (
        remote in {"127.0.0.1", "::1"}
        or remote.startswith("10.")
        or remote.startswith("172.")
        or remote.startswith("192.168.")
    )
    if is_proxied:
        forwarded = (request.headers.get("X-Real-IP") or "").strip()
        if forwarded:
            return forwarded
    return remote


def check_request(path):
    """返回 (是否放行, 建议等待秒数, 桶名)。未启用或未命中策略时恒放行。"""
    if not RATE_LIMIT_ENABLED:
        return True, 0.0, ""
    policy = resolve_policy(path)
    if policy is None:
        return True, 0.0, ""
    name, limit = policy
    allowed, retry_after = _get_limiter(name, limit).hit(resolve_client_key())
    return allowed, retry_after, name


def metrics_snapshot():
    with _limiters_lock:
        return {name: limiter.snapshot() for name, limiter in _limiters.items()}


def reset_all():
    """测试辅助：清空所有桶与计数。"""
    with _limiters_lock:
        _limiters.clear()


def is_enabled():
    return bool(RATE_LIMIT_ENABLED)
