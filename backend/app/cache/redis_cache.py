"""Redis-backed caching with versioned-namespace invalidation, a fixed-window rate limiter and a token denylist.

Invalidation model
------------------
Each data *domain* (``jobs``, ``applications`` …) owns a version counter in Redis. A cached
value's key embeds the current versions of every domain it depends on, e.g.

    cache:v1:recruiter-dashboard:applications=12:interviews=4:jobs=9:<param-hash>

Any write to a domain does ``INCR cache:ver:<domain>``; all keys built from the old version
become unreachable instantly (and expire through their TTL). This is O(1), has no
"delete by pattern" scans, and cannot miss a dependent key.

Failure model
-------------
Redis is an optimisation, not a source of truth. Every operation is fail-open: on a Redis
error we log a warning and compute the value directly. A short circuit-breaker avoids paying
a connection timeout on every request while Redis is down.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

_KEY_PREFIX = "cache:v1"
_BREAKER_SECONDS = 15.0


class _Breaker:
    """Process-wide circuit breaker for Redis: after a failure, skip Redis for a few seconds instead of paying the connect
    timeout on every request (cache, rate limiter and token denylist all consult it)."""

    def __init__(self) -> None:
        self.down_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self.down_until

    def trip(self) -> None:
        self.down_until = time.monotonic() + _BREAKER_SECONDS


redis_breaker = _Breaker()


class CacheDomain(enum.StrEnum):
    SKILLS = "skills"
    JOBS = "jobs"  # postings (public search, company lists)
    CANDIDATES = "candidates"
    APPLICATIONS = "applications"
    INTERVIEWS = "interviews"
    MATCHES = "matches"  # candidate_job_matches (recommendations, ranked candidates)
    USERS = "users"


class Cache:
    def __init__(self, redis: Redis | None, *, enabled: bool = True, default_ttl: int = 300) -> None:
        self._redis = redis
        self.enabled = enabled and redis is not None
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0

    @property
    def redis(self) -> Redis | None:
        return self._redis

    @property
    def _down_until(self) -> float:  # kept for tests/diagnostics; backed by the shared breaker
        return redis_breaker.down_until

    @_down_until.setter
    def _down_until(self, value: float) -> None:
        redis_breaker.down_until = value

    def _available(self) -> bool:
        return self.enabled and not redis_breaker.is_open()

    def _trip(self, exc: Exception, op: str) -> None:
        redis_breaker.trip()
        logger.warning("redis unavailable; cache bypassed", extra={"op": op, "error": type(exc).__name__})

    async def _versions(self, domains: Iterable[CacheDomain]) -> str:
        assert self._redis is not None
        doms = sorted({d.value for d in domains})
        if not doms:
            return ""
        values = await self._redis.mget([f"cache:ver:{d}" for d in doms])
        return ":".join(
            f"{d}={(v.decode() if isinstance(v, bytes) else v) or 0}"
            for d, v in zip(doms, values, strict=True)
        )

    @staticmethod
    def _param_hash(params: dict[str, Any] | None) -> str:
        raw = json.dumps(params or {}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def get_or_set(
        self,
        name: str,
        domains: Iterable[CacheDomain],
        compute: Callable[[], Awaitable[T]],
        *,
        params: dict[str, Any] | None = None,
        ttl: int | None = None,
        serialize: Callable[[T], Any] = lambda v: v,
        deserialize: Callable[[Any], T] = lambda v: v,
    ) -> T:
        """Return the cached value for ``name``+``params`` or compute, store and return it."""
        if not self._available():
            return await compute()
        domains = list(domains)
        key: str | None = None
        try:
            assert self._redis is not None
            versions = await self._versions(domains)
            key = f"{_KEY_PREFIX}:{name}:{versions}:{self._param_hash(params)}"
            raw = await self._redis.get(key)
            if raw is not None:
                self.hits += 1
                logger.debug("cache hit", extra={"cache_key": name})
                return deserialize(json.loads(raw))
        except RedisError as exc:
            self._trip(exc, "get")
            return await compute()

        self.misses += 1
        value = await compute()
        try:
            await self._redis.set(key, json.dumps(serialize(value), default=str), ex=ttl or self.default_ttl)
        except RedisError as exc:
            self._trip(exc, "set")
        return value

    async def invalidate(self, *domains: CacheDomain) -> None:
        if not self._available() or not domains:
            return
        try:
            assert self._redis is not None
            pipe = self._redis.pipeline(transaction=False)
            for d in set(domains):
                pipe.incr(f"cache:ver:{d.value}")
            await pipe.execute()
        except RedisError as exc:
            # Keys embed versions; a missed bump would serve stale data until TTL. Log loudly.
            self._trip(exc, "invalidate")

    async def ping(self) -> bool:
        if self._redis is None:
            return False
        try:
            ok = bool(await self._redis.ping())
            if ok:
                redis_breaker.down_until = 0.0
            return ok
        except RedisError:
            return False


class RateLimiter:
    """Fixed-window limiter (INCR + EXPIRE). Fails open when Redis is unavailable."""

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis

    async def hit(self, bucket: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Register a hit; returns (allowed, retry_after_seconds)."""
        if self._redis is None or redis_breaker.is_open():
            return True, 0
        key = f"ratelimit:{bucket}"
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
        except RedisError as exc:
            redis_breaker.trip()
            logger.warning("rate limiter unavailable; allowing request", extra={"error": type(exc).__name__})
            return True, 0
        if int(count) > limit:
            return False, max(int(ttl), 1)
        return True, 0

    async def retry_after(self, bucket: str, limit: int) -> int:
        """Seconds until ``bucket`` accepts requests again (0 if not blocked). Read-only."""
        if self._redis is None or redis_breaker.is_open():
            return 0
        key = f"ratelimit:{bucket}"
        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.get(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()
        except RedisError as exc:
            redis_breaker.trip()
            logger.warning("rate limiter unavailable; allowing request", extra={"error": type(exc).__name__})
            return 0
        if count is not None and int(count) >= limit:
            return max(int(ttl), 1)
        return 0

    async def reset(self, bucket: str) -> None:
        if self._redis is None or redis_breaker.is_open():
            return
        try:
            await self._redis.delete(f"ratelimit:{bucket}")
        except RedisError:
            redis_breaker.trip()


class TokenDenylist:
    """Revoked access-token ids (``jti``), kept until the token would have expired anyway.

    Best effort by design: if Redis is down the denylist cannot be consulted, access tokens are short-lived
    (minutes) and refresh tokens - the long-lived credential - are revoked in PostgreSQL, the source of truth.
    """

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        if self._redis is None or ttl_seconds <= 0 or redis_breaker.is_open():
            return
        try:
            await self._redis.set(f"denylist:jti:{jti}", b"1", ex=ttl_seconds)
        except RedisError:
            redis_breaker.trip()

    async def is_revoked(self, jti: str) -> bool:
        if self._redis is None or redis_breaker.is_open():
            return False
        try:
            return bool(await self._redis.exists(f"denylist:jti:{jti}"))
        except RedisError:
            redis_breaker.trip()
            return False


_redis_client: Redis | None = None
_cache: Cache | None = None


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1.0, socket_timeout=1.0
        )
    return _redis_client


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        settings = get_settings()
        _cache = Cache(
            get_redis(), enabled=settings.cache_enabled, default_ttl=settings.cache_default_ttl_seconds
        )
    return _cache


def get_denylist() -> TokenDenylist:
    return TokenDenylist(get_redis())


def set_cache(cache: Cache | None) -> None:
    """Override the process-wide cache (tests)."""
    global _cache
    _cache = cache


async def close_redis() -> None:
    global _redis_client, _cache
    if _redis_client is not None:
        await _redis_client.aclose()
    _redis_client = None
    _cache = None
