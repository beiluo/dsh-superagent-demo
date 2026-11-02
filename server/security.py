"""Request security helpers: rate limiting, client identity, headers."""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone

from fastapi import Request


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            candidate = forwarded.split(",", 1)[0].strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class SlidingWindowLimiter:
    """In-memory per-IP limiter plus a process-wide daily budget.

    A single process is assumed.  For a multi-instance deployment, use a shared
    store (Redis) or the platform's rate limiting in front of the service.
    """

    def __init__(self, per_minute: int, per_hour: int, daily_budget: int):
        self.per_minute = max(1, per_minute)
        self.per_hour = max(1, per_hour)
        self.daily_budget = max(1, daily_budget)
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._day: date = datetime.now(timezone.utc).date()
        self._daily_count = 0
        self._last_cleanup = 0.0

    @staticmethod
    def _now(now: float | None = None) -> float:
        return time.monotonic() if now is None else now

    @staticmethod
    def _today(today: date | None = None) -> date:
        return datetime.now(timezone.utc).date() if today is None else today

    def check(
        self,
        key: str,
        *,
        now: float | None = None,
        today: date | None = None,
    ) -> tuple[bool, int, str]:
        """Return ``(allowed, retry_after_seconds, reason)``."""

        current = self._now(now)
        current_day = self._today(today)
        with self._lock:
            if current_day != self._day:
                self._day = current_day
                self._daily_count = 0
            if self._daily_count >= self.daily_budget:
                next_day = datetime.combine(current_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
                seconds = max(1, int((next_day - datetime.now(timezone.utc)).total_seconds()))
                return False, seconds, "daily_budget"

            events = self._events.setdefault(key, deque())
            while events and current - events[0] >= 3600:
                events.popleft()
            minute_count = sum(1 for stamp in events if current - stamp < 60)
            if minute_count >= self.per_minute:
                oldest = next((stamp for stamp in events if current - stamp < 60), current)
                return False, max(1, int(60 - (current - oldest))), "per_minute"
            if len(events) >= self.per_hour:
                return False, max(1, int(3600 - (current - events[0]))), "per_hour"

            events.append(current)
            self._daily_count += 1

            # Periodically drop idle keys so a long-running process does not
            # grow without bound.
            if current - self._last_cleanup > 600:
                self._last_cleanup = current
                for event_key in list(self._events):
                    queue = self._events[event_key]
                    if not queue or current - queue[-1] > 3600:
                        del self._events[event_key]
            return True, 0, "ok"
