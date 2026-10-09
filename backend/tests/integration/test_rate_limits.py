"""Fixed-window rate limiting: the limiter itself and how the API applies it (per client address, per user)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.cache.redis_cache import RateLimiter, get_redis
from app.core.config import get_settings
from tests.helpers import auth, create_job, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, client_from, fast_argon  # noqa: F401

pytestmark = pytest.mark.integration

SEARCH = f"{API}/search/jobs"


@pytest.fixture
def limiter(db: None) -> RateLimiter:
    return RateLimiter(get_redis())


# --- the limiter -------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_hits_up_to_the_limit_are_allowed_and_the_next_is_refused(limiter: RateLimiter) -> None:
    for i in range(5):
        assert await limiter.hit("t", 5, 120) == (True, 0), i
    allowed, retry = await limiter.hit("t", 5, 120)
    assert allowed is False and 1 <= retry <= 120
    assert (await limiter.hit("t", 5, 120))[0] is False, "stays refused for the rest of the window"
    assert int(await get_redis().get("ratelimit:t")) == 7, "refused attempts are counted too"


async def test_buckets_are_independent_and_limits_are_per_call(limiter: RateLimiter) -> None:
    for _ in range(3):
        await limiter.hit("a", 2, 60)
    assert (await limiter.hit("a", 2, 60))[0] is False
    assert await limiter.hit("b", 2, 60) == (True, 0)
    assert await limiter.hit("a", 100, 60) == (True, 0), (
        "the limit is supplied by the caller, so raising it re-admits the bucket"
    )


async def test_the_window_is_fixed_not_sliding(limiter: RateLimiter) -> None:
    await limiter.hit("w", 100, 100)
    first = await get_redis().ttl("ratelimit:w")
    assert 0 < first <= 100
    for _ in range(10):
        await limiter.hit("w", 100, 100)
    later = await get_redis().ttl("ratelimit:w")
    assert 0 < later <= first, "further hits never extend the window"
    allowed, retry = await RateLimiter(get_redis()).hit("w", 5, 100)
    assert allowed is False and 0 < retry <= first, "Retry-After is the time left in the current window"


async def test_the_counter_resets_when_the_window_expires(limiter: RateLimiter) -> None:
    for _ in range(4):
        await limiter.hit("exp", 3, 100)
    assert (await limiter.hit("exp", 3, 100))[0] is False
    await get_redis().pexpire("ratelimit:exp", 1)  # the window ends
    for _ in range(2000):  # Redis expires lazily on access; poll (no sleeping) until the key is gone
        if not await get_redis().exists("ratelimit:exp"):
            break
    assert await limiter.hit("exp", 3, 100) == (True, 0)
    assert int(await get_redis().get("ratelimit:exp")) == 1


async def test_retry_after_is_read_only(limiter: RateLimiter) -> None:
    assert await limiter.retry_after("ro", 3) == 0
    for _ in range(2):
        await limiter.hit("ro", 3, 90)
    assert await limiter.retry_after("ro", 3) == 0, "below the limit"
    await limiter.hit("ro", 3, 90)
    wait = await limiter.retry_after("ro", 3)
    assert 0 < wait <= 90, "at the limit callers are told to wait"
    assert int(await get_redis().get("ratelimit:ro")) == 3, "reading did not count as a hit"


async def test_reset_clears_the_bucket(limiter: RateLimiter) -> None:
    for _ in range(5):
        await limiter.hit("r", 2, 60)
    await limiter.reset("r")
    assert await limiter.hit("r", 2, 60) == (True, 0)
    await limiter.reset("never-used")


# --- the API -----------------------------------------------------------------------------------------------------------------------------------------------------------


def limit(monkeypatch: pytest.MonkeyPatch, name: str, attempts: int, window: int = 90) -> None:
    monkeypatch.setattr(get_settings(), f"{name}_rate_limit_attempts", attempts)
    monkeypatch.setattr(get_settings(), f"{name}_rate_limit_window_seconds", window)


async def test_search_is_limited_per_client_with_the_standard_envelope(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "search", 3)
    async with client_from("10.9.0.1") as a, client_from("10.9.0.2") as b:
        for _ in range(3):
            assert (await a.get(SEARCH)).status_code == 200
        r = await a.get(SEARCH)
        err = assert_error(r, 429, "RATE_LIMITED")
        retry = int(r.headers["retry-after"])
        assert (
            1 <= retry <= 90
            and err["details"] == {"retry_after_seconds": retry}
            and "slow down" in err["message"]
        )
        assert (await a.get(f"{API}/search/candidates")).status_code in (
            401,
            429,
        )  # the limit covers the whole search router
        assert (await b.get(SEARCH)).status_code == 200, "another address has its own budget"
    assert (await client.get(SEARCH)).status_code == 200, "...and so does the default test address"


async def test_the_window_reopens_after_it_elapses(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "search", 2)
    async with client_from("10.9.1.1") as a:
        assert [(await a.get(SEARCH)).status_code for _ in range(3)] == [200, 200, 429]
        await get_redis().delete("ratelimit:search:10.9.1.1")  # what the passing of the window does
        assert (await a.get(SEARCH)).status_code == 200


async def test_authenticated_callers_are_limited_per_user_not_per_address(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = await register_candidate(client), await register_candidate(client)
    limit(monkeypatch, "search", 3)
    async with client_from("10.9.2.1") as shared:  # one office, one address, two people
        assert [(await shared.get(SEARCH, headers=a["h"])).status_code for _ in range(4)] == [
            200,
            200,
            200,
            429,
        ]
        assert (await shared.get(SEARCH, headers=b["h"])).status_code == 200, "B has not used B's budget"
        assert (await shared.get(SEARCH, headers=b["h"])).status_code == 200
        assert (await shared.get(SEARCH, headers=b["h"])).status_code == 200
        assert (await shared.get(SEARCH, headers=b["h"])).status_code == 429
        assert (await shared.get(SEARCH)).status_code == 200, (
            "anonymous traffic from that address has yet another bucket"
        )
    keys = {k.decode() async for k in get_redis().scan_iter(match="ratelimit:search:*")}
    assert keys == {
        f"ratelimit:search:user:{a['user']['id']}",
        f"ratelimit:search:user:{b['user']['id']}",
        "ratelimit:search:10.9.2.1",
    }


async def test_a_user_keeps_their_budget_when_the_address_changes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await register_candidate(client)
    limit(monkeypatch, "search", 2)
    async with client_from("10.9.3.1") as home, client_from("10.9.3.2") as mobile:
        assert (await home.get(SEARCH, headers=a["h"])).status_code == 200
        assert (await mobile.get(SEARCH, headers=a["h"])).status_code == 200
        assert (await home.get(SEARCH, headers=a["h"])).status_code == 429


async def test_a_bad_token_falls_back_to_the_address_bucket_and_cannot_pick_a_victim(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = await register_candidate(client)
    limit(monkeypatch, "search", 2)
    from app.core.security import create_access_token

    forged, _ = create_access_token(victim["user"]["id"], "CANDIDATE")
    forged = forged[:-3] + ("AAA" if not forged.endswith("AAA") else "BBB")  # signature no longer verifies
    async with client_from("10.9.4.1") as attacker:
        assert (
            await attacker.get(SEARCH, headers=auth(forged))
        ).status_code == 401  # rejected by authentication ...
    assert await get_redis().get(f"ratelimit:search:user:{victim['user']['id']}") is None, (
        "... and it never touched the victim's bucket"
    )
    async with client_from("10.9.4.2") as honest:
        assert [(await honest.get(SEARCH, headers=victim["h"])).status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]


async def test_expensive_endpoints_are_limited_per_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = await register_employer(client)
    other = await register_employer(client)
    mine, theirs = await create_job(client, rec, publish=True), await create_job(client, other, publish=True)
    limit(monkeypatch, "expensive", 2)
    url = f"{API}/matches/jobs/{mine['id']}/refresh"
    async with client_from("10.9.5.1") as c:
        assert [(await c.post(url, headers=rec["h"])).status_code for _ in range(2)] == [202, 202]
        r = await c.post(url, headers=rec["h"])
        err = assert_error(r, 429, "RATE_LIMITED")
        assert int(r.headers["retry-after"]) >= 1 and err["details"]["retry_after_seconds"] >= 1
        # another recruiter behind the same address is not throttled by this one
        assert (
            await c.post(f"{API}/matches/jobs/{theirs['id']}/refresh", headers=other["h"])
        ).status_code == 202
    # candidates have their own endpoint and budget
    cand = await register_candidate(client)
    async with client_from("10.9.5.2") as c:
        assert [
            (await c.post(f"{API}/recommendations/refresh", headers=cand["h"])).status_code for _ in range(3)
        ] == [202, 202, 429]


async def test_limits_are_read_from_the_settings_on_every_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with client_from("10.9.6.1") as c:
        assert [(await c.get(SEARCH)).status_code for _ in range(3)] == [200, 200, 200]
        limit(monkeypatch, "search", 3)
        assert (await c.get(SEARCH)).status_code == 429, "the same bucket, judged against the stricter limit"
        limit(monkeypatch, "search", 1000)
        assert (await c.get(SEARCH)).status_code == 200


async def test_rate_limited_responses_carry_security_headers_and_a_request_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "search", 1)
    async with client_from("10.9.7.1") as c:
        await c.get(SEARCH)
        r: Any = await c.get(SEARCH, headers={"X-Request-ID": "trace-me-123"})
    assert (
        r.status_code == 429
        and r.headers["x-request-id"] == "trace-me-123"
        and r.json()["error"]["request_id"] == "trace-me-123"
    )
    assert r.headers["x-content-type-options"] == "nosniff" and "retry-after" in r.headers
