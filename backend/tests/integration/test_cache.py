"""The Redis cache (versioned namespaces), the circuit breaker, and fail-open behaviour of cache, limiter and denylist."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from redis.exceptions import RedisError

from app.cache.redis_cache import (
    Cache,
    CacheDomain,
    RateLimiter,
    TokenDenylist,
    get_cache,
    get_redis,
    redis_breaker,
)
from tests.helpers_spine import fast_argon  # noqa: F401

pytestmark = pytest.mark.integration


class Counter:
    def __init__(self, value: Any = None) -> None:
        self.calls = 0
        self.value = value if value is not None else {"n": 1}

    async def __call__(self) -> Any:
        self.calls += 1
        return self.value


@pytest.fixture
def cache(db: None) -> Cache:
    return Cache(get_redis(), default_ttl=300)


# --- hits, misses, keys, TTL ---------------------------------------------------------------------------------------------------------------------------------------


async def test_get_or_set_computes_once_then_hits(cache: Cache) -> None:
    compute = Counter({"items": [1, 2, 3]})
    first = await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"q": "x"})
    second = await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"q": "x"})
    assert first == second == {"items": [1, 2, 3]} and compute.calls == 1
    assert (cache.misses, cache.hits) == (1, 1)
    third = await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"q": "y"})
    assert compute.calls == 2 and (cache.misses, cache.hits) == (2, 1) and third == first


async def test_parameters_are_part_of_the_key_in_any_order(cache: Cache) -> None:
    compute = Counter()
    await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"a": 1, "b": [1, 2], "c": None})
    await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"c": None, "b": [1, 2], "a": 1})
    assert compute.calls == 1, "dict order must not matter"
    await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={"a": 1, "b": [2, 1], "c": None})
    await cache.get_or_set("other", [CacheDomain.JOBS], compute, params={"a": 1, "b": [1, 2], "c": None})
    await cache.get_or_set("probe", [CacheDomain.JOBS], compute)
    await cache.get_or_set("probe", [CacheDomain.JOBS], compute, params={})
    assert compute.calls == 4, "None and {} share an entry; everything else is distinct"


async def test_unserialisable_parameter_types_still_produce_stable_keys(cache: Cache) -> None:
    import uuid
    from datetime import date

    compute = Counter()
    params = {"id": uuid.UUID(int=1), "day": date(2026, 1, 1)}
    await cache.get_or_set("probe", [], compute, params=params)
    await cache.get_or_set("probe", [], compute, params=dict(params))
    assert compute.calls == 1


async def test_entries_expire_with_the_requested_ttl(cache: Cache) -> None:
    await cache.get_or_set("short", [CacheDomain.JOBS], Counter(), ttl=7)
    await cache.get_or_set("default", [CacheDomain.JOBS], Counter())
    keys = {k.decode(): await get_redis().ttl(k) async for k in get_redis().scan_iter(match="cache:v1:*")}
    ttls = {("short" if ":short:" in k else "default"): v for k, v in keys.items()}
    assert 0 < ttls["short"] <= 7 and 250 < ttls["default"] <= 300


async def test_falsy_values_are_cached_too(cache: Cache) -> None:
    for value in (None, [], {}, 0, False, ""):
        compute = Counter()
        compute.value = value

        async def go(c: Counter = compute, v: Any = value) -> Any:
            return await cache.get_or_set(f"falsy-{v!r}", [], c)

        assert await go() == value and await go() == value and compute.calls == 1, repr(value)


async def test_serialize_and_deserialize_hooks(cache: Cache) -> None:
    from decimal import Decimal

    compute = Counter(Decimal("1.50"))
    ser, de = (lambda v: str(v)), (lambda raw: Decimal(raw))
    a = await cache.get_or_set("dec", [], compute, serialize=ser, deserialize=de)
    b = await cache.get_or_set("dec", [], compute, serialize=ser, deserialize=de)
    assert a == b == Decimal("1.50") and compute.calls == 1
    [key] = [k async for k in get_redis().scan_iter(match="cache:v1:dec:*")]
    assert json.loads(await get_redis().get(key)) == "1.50"


async def test_unreadable_entries_are_treated_as_misses_and_overwritten(cache: Cache) -> None:
    compute = Counter({"ok": True})
    await cache.get_or_set("fragile", [CacheDomain.JOBS], compute)
    [key] = [k async for k in get_redis().scan_iter(match="cache:v1:fragile:*")]
    for garbage in (b"{not json", b'{"ok": true', b""):
        await get_redis().set(key, garbage, ex=60)
        assert await cache.get_or_set("fragile", [CacheDomain.JOBS], compute) == {"ok": True}
        assert json.loads(await get_redis().get(key)) == {"ok": True}, "the bad entry was replaced"
    # a schema change: valid JSON that the new deserializer rejects
    await get_redis().set(key, json.dumps({"old": "shape"}), ex=60)

    def strict(raw: dict[str, Any]) -> dict[str, Any]:
        return {"ok": raw["ok"]}  # KeyError for the old shape

    calls = compute.calls
    assert await cache.get_or_set("fragile", [CacheDomain.JOBS], compute, deserialize=strict) == {"ok": True}
    assert compute.calls == calls + 1


# --- namespace invalidation --------------------------------------------------------------------------------------------------------------------------------------------


async def test_invalidating_a_domain_makes_its_entries_unreachable(cache: Cache) -> None:
    jobs, users = Counter({"d": "jobs"}), Counter({"d": "users"})
    await cache.get_or_set("a", [CacheDomain.JOBS], jobs)
    await cache.get_or_set("b", [CacheDomain.USERS], users)
    await cache.invalidate(CacheDomain.JOBS)
    await cache.get_or_set("a", [CacheDomain.JOBS], jobs)
    await cache.get_or_set("b", [CacheDomain.USERS], users)
    assert (jobs.calls, users.calls) == (2, 1), "only the invalidated namespace is recomputed"
    assert (
        int(await get_redis().get("cache:ver:jobs")) == 1 and await get_redis().get("cache:ver:users") is None
    )


async def test_entries_depending_on_several_domains_die_with_any_of_them(cache: Cache) -> None:
    compute = Counter()
    domains = [CacheDomain.MATCHES, CacheDomain.JOBS, CacheDomain.APPLICATIONS]
    await cache.get_or_set("multi", domains, compute)
    await cache.get_or_set("multi", list(reversed(domains)), compute)
    assert compute.calls == 1, "the order in which domains are listed is irrelevant"
    for domain in (CacheDomain.MATCHES, CacheDomain.JOBS, CacheDomain.APPLICATIONS):
        before = compute.calls
        await cache.invalidate(domain)
        await cache.get_or_set("multi", domains, compute)
        assert compute.calls == before + 1, domain
    await cache.invalidate(CacheDomain.SKILLS)
    await cache.get_or_set("multi", domains, compute)
    assert compute.calls == 4, "unrelated domains do not matter"


async def test_invalidate_many_at_once_and_repeatedly(cache: Cache) -> None:
    await cache.invalidate(CacheDomain.JOBS, CacheDomain.MATCHES, CacheDomain.JOBS)
    assert (
        int(await get_redis().get("cache:ver:jobs")) == 1
        and int(await get_redis().get("cache:ver:matches")) == 1
    )
    await cache.invalidate(CacheDomain.JOBS)
    await cache.invalidate(CacheDomain.JOBS)
    assert int(await get_redis().get("cache:ver:jobs")) == 3
    await cache.invalidate()  # nothing to do
    assert int(await get_redis().get("cache:ver:matches")) == 1


async def test_old_entries_are_not_deleted_just_orphaned(cache: Cache) -> None:
    await cache.get_or_set("orphan", [CacheDomain.JOBS], Counter())
    [old] = [k async for k in get_redis().scan_iter(match="cache:v1:orphan:*")]
    await cache.invalidate(CacheDomain.JOBS)
    await cache.get_or_set("orphan", [CacheDomain.JOBS], Counter())
    keys = [k async for k in get_redis().scan_iter(match="cache:v1:orphan:*")]
    assert old in keys and len(keys) == 2 and await get_redis().ttl(old) > 0, (
        "stale entries simply expire through their TTL"
    )


async def test_a_disabled_cache_always_computes(db: None) -> None:
    for disabled in (Cache(get_redis(), enabled=False), Cache(None)):
        compute = Counter()
        await disabled.get_or_set("x", [CacheDomain.JOBS], compute)
        await disabled.get_or_set("x", [CacheDomain.JOBS], compute)
        await disabled.invalidate(CacheDomain.JOBS)
        assert compute.calls == 2 and (disabled.hits, disabled.misses) == (0, 0)
    assert await get_redis().keys("cache:*") == []


# --- failure model ---------------------------------------------------------------------------------------------------------------------------------------------------------


class DeadRedis:
    """Every command raises, and every attempt is counted."""

    def __init__(self) -> None:
        self.attempts = 0

    def _boom(self, *a: Any, **k: Any) -> Any:
        self.attempts += 1
        raise RedisError("connection refused")

    async def get(self, *a: Any, **k: Any) -> Any:
        self._boom()

    async def mget(self, *a: Any, **k: Any) -> Any:
        self._boom()

    async def set(self, *a: Any, **k: Any) -> Any:
        self._boom()

    async def exists(self, *a: Any, **k: Any) -> Any:
        self._boom()

    async def delete(self, *a: Any, **k: Any) -> Any:
        self._boom()

    async def ping(self, *a: Any, **k: Any) -> Any:
        self._boom()

    def pipeline(self, *a: Any, **k: Any) -> Any:
        dead = self

        class P:
            def incr(self, *a: Any, **k: Any) -> None:
                return None

            def expire(self, *a: Any, **k: Any) -> None:
                return None

            def ttl(self, *a: Any, **k: Any) -> None:
                return None

            def get(self, *a: Any, **k: Any) -> None:
                return None

            async def execute(self) -> Any:
                dead._boom()

        return P()


async def test_the_cache_fails_open_and_trips_the_breaker(db: None) -> None:
    dead = DeadRedis()
    cache = Cache(dead)  # type: ignore[arg-type]
    compute = Counter({"fresh": True})
    assert await cache.get_or_set("x", [CacheDomain.JOBS], compute) == {"fresh": True}
    assert compute.calls == 1 and dead.attempts == 1 and redis_breaker.is_open()
    # while the breaker is open Redis is not even tried
    for _ in range(3):
        assert await cache.get_or_set("x", [CacheDomain.JOBS], compute) == {"fresh": True}
    await cache.invalidate(CacheDomain.JOBS)
    assert dead.attempts == 1 and compute.calls == 4
    # after the cool-down it probes again (once) and re-trips on failure
    redis_breaker.down_until = time.monotonic() - 1
    await cache.get_or_set("x", [CacheDomain.JOBS], compute)
    assert dead.attempts == 2 and redis_breaker.is_open()


async def test_a_failing_write_after_the_computation_still_returns_the_value(db: None) -> None:
    class WriteFails(DeadRedis):
        async def mget(self, keys: Any) -> Any:
            return [None] * len(keys)

        async def get(self, key: Any) -> Any:
            return None

    cache = Cache(WriteFails())  # type: ignore[arg-type]
    compute = Counter({"v": 1})
    assert await cache.get_or_set("x", [CacheDomain.JOBS], compute) == {"v": 1}
    assert cache.misses == 1 and redis_breaker.is_open()


async def test_a_failing_invalidation_never_raises(db: None) -> None:
    cache = Cache(DeadRedis())  # type: ignore[arg-type]
    await cache.invalidate(CacheDomain.JOBS, CacheDomain.MATCHES)
    assert redis_breaker.is_open()


async def test_ping_reports_health_and_closes_the_breaker_when_redis_is_back(db: None) -> None:
    assert await Cache(DeadRedis()).ping() is False  # type: ignore[arg-type]
    assert await Cache(None).ping() is False
    redis_breaker.trip()
    assert await Cache(get_redis()).ping() is True and not redis_breaker.is_open()


async def test_the_breaker_is_shared_by_cache_limiter_and_denylist(db: None) -> None:
    dead = DeadRedis()
    await Cache(dead).get_or_set("x", [], Counter())  # type: ignore[arg-type]
    assert redis_breaker.is_open()
    attempts = dead.attempts
    assert await RateLimiter(dead).hit("b", 1, 60) == (True, 0)  # type: ignore[arg-type]
    assert await RateLimiter(dead).retry_after("b", 1) == 0  # type: ignore[arg-type]
    await RateLimiter(dead).reset("b")  # type: ignore[arg-type]
    await TokenDenylist(dead).revoke("jti", 60)  # type: ignore[arg-type]
    assert await TokenDenylist(dead).is_revoked("jti") is False  # type: ignore[arg-type]
    assert dead.attempts == attempts, "nobody pays a timeout while the breaker is open"


async def test_limiter_and_denylist_fail_open_and_trip_the_breaker(db: None) -> None:
    assert await RateLimiter(DeadRedis()).hit("b", 1, 60) == (True, 0)  # type: ignore[arg-type]
    assert redis_breaker.is_open()
    redis_breaker.down_until = 0.0
    assert await RateLimiter(DeadRedis()).retry_after("b", 1) == 0  # type: ignore[arg-type]
    assert redis_breaker.is_open()
    redis_breaker.down_until = 0.0
    await RateLimiter(DeadRedis()).reset("b")  # type: ignore[arg-type]
    assert redis_breaker.is_open()
    redis_breaker.down_until = 0.0
    await TokenDenylist(DeadRedis()).revoke("jti", 60)  # type: ignore[arg-type]
    assert redis_breaker.is_open()
    redis_breaker.down_until = 0.0
    assert await TokenDenylist(DeadRedis()).is_revoked("jti") is False  # type: ignore[arg-type]
    assert redis_breaker.is_open()


async def test_without_redis_the_helpers_are_permissive(db: None) -> None:
    assert await RateLimiter(None).hit("b", 1, 60) == (True, 0)
    assert await RateLimiter(None).retry_after("b", 1) == 0
    await RateLimiter(None).reset("b")
    await TokenDenylist(None).revoke("j", 10)
    assert await TokenDenylist(None).is_revoked("j") is False


async def test_the_process_wide_cache_uses_settings(db: None) -> None:
    from app.core.config import get_settings

    cache = get_cache()
    assert (
        cache.enabled
        and cache.default_ttl == get_settings().cache_default_ttl_seconds
        and cache.redis is get_redis()
    )
