"""Per-client hourly and shared daily limits on the routes that call the model."""

import math
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from fastapi import Request

from backedcv.api.errors import ApiError
from backedcv.api.retention import utc_now
from backedcv.settings import get_settings

HOUR = timedelta(hours=1)


class RunLimiter:
    """Counts the model runs in memory, so the counts start again with the process."""

    def __init__(
        self,
        per_hour: int,
        per_day: int,
        clock: Callable[[], datetime] = utc_now,
        *,
        hourly_code: str = "rate_limited",
        daily_code: str = "daily_limit_reached",
        daily_title: str = "The daily limit of analyses has been reached.",
    ) -> None:
        self.per_hour, self.per_day = per_hour, per_day
        self._clock = clock
        self._hourly_code, self._daily_code, self._daily_title = (
            hourly_code,
            daily_code,
            daily_title,
        )
        self._by_client: dict[str, deque[datetime]] = {}
        self._day: date | None = None
        self._day_runs = 0
        self._swept: datetime | None = None

    def check(self, client: str) -> None:
        """Counts one model run for `client`, or raises the 429 that says when to try again."""
        now = self._clock()
        self._forget_idle_clients(now)
        if now.date() != self._day:
            self._day, self._day_runs = now.date(), 0
        if self._day_runs >= self.per_day:
            midnight = datetime.combine(now.date() + timedelta(days=1), time.min, UTC)
            raise ApiError(
                429,
                self._daily_code,
                self._daily_title,
                f"The limit resets at midnight UTC, in {_wait(midnight - now)}.",
            )
        runs = self._by_client.setdefault(client, deque())
        while runs and now - runs[0] >= HOUR:
            runs.popleft()
        if len(runs) >= self.per_hour:
            wait = _wait(runs[0] + HOUR - now)
            raise ApiError(
                429,
                self._hourly_code,
                "Too many requests from this network.",
                f"At most {self.per_hour} requests an hour are allowed. Try again in {wait}.",
            )
        runs.append(now)
        self._day_runs += 1

    def _forget_idle_clients(self, now: datetime) -> None:
        """Once an hour, drops the clients with no run in the last hour, so the table of clients
        does not grow for as long as the process lives."""
        if self._swept is not None and now - self._swept < HOUR:
            return
        self._swept = now
        self._by_client = {
            client: runs
            for client, runs in self._by_client.items()
            if runs and now - runs[-1] < HOUR
        }


def _wait(delta: timedelta) -> str:
    """A short, readable wait: whole minutes, or whole hours when it is more than two hours."""
    minutes = max(1, math.ceil(delta.total_seconds() / 60))
    if minutes > 120:
        return f"{math.ceil(minutes / 60)} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def client_address(request: Request) -> str:
    """The address the per-client limits count. Behind a proxy that writes the caller's address
    in a header of its own (`BACKEDCV_CLIENT_IP_HEADER`, such as CF-Connecting-IP behind
    Cloudflare), that header is used: a caller can set the left end of X-Forwarded-For."""
    header = get_settings().client_ip_header
    address = request.headers.get(header, "").strip() if header else ""
    return address or (request.client.host if request.client else "unknown")


def count_model_run(request: Request) -> None:
    """Counts one model run for the client, or raises the 429. Call it after validation and stage
    checks, so a refused request uses no quota. It has no await, so check and count cannot
    interleave with another request."""
    request.app.state.limiter.check(client_address(request))
