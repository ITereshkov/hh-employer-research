import pytest
import asyncio

from hh_parser.api.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        limiter = RateLimiter(per_minute=10, per_day=100)
        for _ in range(5):
            await limiter.acquire()
        assert limiter.daily_remaining >= 90

    @pytest.mark.asyncio
    async def test_acquire_respects_minute_limit(self):
        limiter = RateLimiter(per_minute=2, per_day=100)
        await limiter.acquire()
        await limiter.acquire()
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.05
