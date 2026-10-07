import asyncio
import time


class RateLimiter:
    def __init__(self, per_minute: int = 25, per_day: int = 1800):
        self._per_minute = per_minute
        self._per_day = per_day
        self._minute_tokens = float(per_minute)
        self._day_tokens = float(per_day)
        self._last_refill = time.monotonic()
        self._day_start = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self._minute_tokens >= 1.0 and self._day_tokens >= 1.0:
                    self._minute_tokens -= 1.0
                    self._day_tokens -= 1.0
                    return
                wait = min(
                    (1.0 - self._minute_tokens) * (60.0 / self._per_minute),
                    (1.0 - self._day_tokens) * (86400.0 / self._per_day),
                )
                await asyncio.sleep(max(wait, 0.1))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._minute_tokens = min(
            self._per_minute, self._minute_tokens + elapsed * (self._per_minute / 60.0)
        )
        self._last_refill = now

        day_elapsed = time.time() - self._day_start
        if day_elapsed >= 86400:
            self._day_tokens = float(self._per_day)
            self._day_start = time.time()

    @property
    def daily_remaining(self) -> int:
        return int(self._day_tokens)
