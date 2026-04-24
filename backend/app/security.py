"""Lightweight security and anti-abuse helpers for public demos."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request, status

from app.config.settings import settings


class ChatStreamLimiter:
    """Simple sliding-window rate limit plus concurrency guard."""

    def __init__(self):
        self._lock = threading.RLock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._active: dict[str, int] = defaultdict(int)

    def acquire(self, key: str) -> Callable[[], None]:
        now = time.monotonic()
        window = max(30, int(settings.security.chat_rate_limit_window_seconds))
        limit = max(1, int(settings.security.chat_rate_limit_count))
        concurrent = max(1, int(settings.security.chat_max_concurrent_per_ip))

        with self._lock:
            hits = self._hits[key]
            cutoff = now - window
            while hits and hits[0] < cutoff:
                hits.popleft()

            if len(hits) >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="当前访问过于频繁，请稍后再试。",
                )

            if self._active[key] >= concurrent:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="当前并发请求过多，请等待上一个回答完成。",
                )

            hits.append(now)
            self._active[key] += 1

        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            with self._lock:
                current = self._active.get(key, 0)
                if current <= 1:
                    self._active.pop(key, None)
                else:
                    self._active[key] = current - 1
            released = True

        return release


chat_stream_limiter = ChatStreamLimiter()


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def enforce_public_api_request(request: Request) -> None:
    """Public API must come through the trusted reverse proxy."""
    expected_token = settings.security.proxy_shared_token.strip()
    if expected_token:
        provided_token = request.headers.get("x-clinirag-proxy-token", "").strip()
        if provided_token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

    allowed_origins = set(settings.security.allowed_origins)
    origin = request.headers.get("origin", "").strip()
    if origin and allowed_origins and origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )


def require_admin_api_key(request: Request) -> None:
    """Management endpoints require a separate admin API key."""
    expected_key = settings.security.admin_api_key.strip()
    provided_key = request.headers.get("x-admin-api-key", "").strip()
    if not expected_key or provided_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key required",
        )
