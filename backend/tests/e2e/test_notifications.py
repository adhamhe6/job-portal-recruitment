"""In-app notification centre: listing, counters, read state, ownership and idempotent staging."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.db.models import NotificationType
from app.services.notifications import NotificationService
from tests.helpers import create_job, register_candidate, register_employer
from tests.helpers_spine import API, apply_job, assert_error, fast_argon, scalar, sql  # noqa: F401

pytestmark = pytest.mark.e2e

N = f"{API}/notifications"


async def seed(user_id: str, count: int, *, prefix: str = "n") -> list[uuid.UUID]:
    """``count`` notifications, ``n0`` the oldest ... newest last, one minute apart."""
    ids = []
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(count):
        nid = uuid.uuid4()
        ids.append(nid)
        await sql(
            "INSERT INTO notifications (id, user_id, type, title, message, created_at, dedupe_key) VALUES (:i, :u, 'APPLICATION_SUBMITTED', :t, 'm', :c, :k)",
            i=nid,
            u=uuid.UUID(user_id),
            t=f"{prefix}{i}",
            c=base + timedelta(minutes=i),
            k=f"{prefix}-{i}",
        )
    return ids


async def test_list_is_newest_first_and_paginated(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    await sql("DELETE FROM notifications")
    await seed(cand["user"]["id"], 7)
    r = await client.get(N, headers=cand["h"], params={"page_size": 3})
    body = r.json()
    assert r.status_code == 200 and (body["total"], body["pages"], body["page"], body["page_size"]) == (
        7,
        3,
        1,
        3,
    )
    assert [n["title"] for n in body["items"]] == ["n6", "n5", "n4"]
    assert [
        n["title"]
        for n in (await client.get(N, headers=cand["h"], params={"page_size": 3, "page": 3})).json()["items"]
    ] == ["n0"]
    assert (await client.get(N, headers=cand["h"], params={"page": 9})).json()["items"] == []
    item = body["items"][0]
    assert set(item) == {
        "id",
        "type",
        "title",
        "message",
        "is_read",
        "read_at",
        "job_id",
        "application_id",
        "interview_id",
        "resume_id",
        "created_at",
    }
    assert item["is_read"] is False and item["read_at"] is None
    assert "dedupe_key" not in item and "user_id" not in item
    for bad in ({"page": 0}, {"page_size": 101}, {"unread_only": "maybe"}):
        assert_error(await client.get(N, headers=cand["h"], params=bad), 422, "VALIDATION_ERROR")


async def test_users_only_see_their_own_notifications(client: AsyncClient) -> None:
    a, b = await register_candidate(client), await register_candidate(client)
    await sql("DELETE FROM notifications")
    await seed(a["user"]["id"], 2, prefix="a")
    await seed(b["user"]["id"], 3, prefix="b")
    assert [n["title"] for n in (await client.get(N, headers=a["h"])).json()["items"]] == ["a1", "a0"]
    assert (await client.get(f"{N}/unread-count", headers=b["h"])).json() == {"unread": 3}
    assert_error(await client.get(N), 401, "UNAUTHORIZED")
    assert_error(await client.get(f"{N}/unread-count"), 401, "UNAUTHORIZED")


async def test_unread_count_unread_filter_and_marking_read(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    await sql("DELETE FROM notifications")
    ids = await seed(cand["user"]["id"], 4)
    assert (await client.get(f"{N}/unread-count", headers=cand["h"])).json() == {"unread": 4}
    r = await client.post(f"{N}/{ids[1]}/read", headers=cand["h"])
    assert (
        r.status_code == 200
        and r.json()["is_read"] is True
        and r.json()["read_at"]
        and r.json()["title"] == "n1"
    )
    first_read_at = r.json()["read_at"]
    again = await client.post(f"{N}/{ids[1]}/read", headers=cand["h"])
    assert again.status_code == 200 and again.json()["read_at"] == first_read_at, (
        "marking twice is harmless and keeps the original timestamp"
    )
    assert (await client.get(f"{N}/unread-count", headers=cand["h"])).json() == {"unread": 3}
    unread = (await client.get(N, headers=cand["h"], params={"unread_only": True})).json()
    assert unread["total"] == 3 and [n["title"] for n in unread["items"]] == ["n3", "n2", "n0"]
    assert (await client.get(N, headers=cand["h"])).json()["total"] == 4, (
        "read notifications stay in the list"
    )


async def test_mark_all_read(client: AsyncClient) -> None:
    cand, other = await register_candidate(client), await register_candidate(client)
    await sql("DELETE FROM notifications")
    await seed(cand["user"]["id"], 5, prefix="c")
    await seed(other["user"]["id"], 2, prefix="o")
    r = await client.post(f"{N}/read-all", headers=cand["h"])
    assert r.status_code == 200 and r.json() == {"unread": 0}
    assert (await client.get(f"{N}/unread-count", headers=cand["h"])).json() == {"unread": 0}
    assert (await client.get(f"{N}/unread-count", headers=other["h"])).json() == {"unread": 2}, (
        "other users are untouched"
    )
    assert (await client.post(f"{N}/read-all", headers=cand["h"])).json() == {"unread": 0}
    assert (
        await scalar(
            "SELECT count(*) FROM notifications WHERE user_id = :u AND read_at IS NOT NULL",
            u=uuid.UUID(cand["user"]["id"]),
        )
        == 5
    )


async def test_other_users_notification_ids_are_not_found(client: AsyncClient) -> None:
    a, b = await register_candidate(client), await register_candidate(client)
    await sql("DELETE FROM notifications")
    [nid] = await seed(a["user"]["id"], 1)
    assert_error(await client.post(f"{N}/{nid}/read", headers=b["h"]), 404, "NOTIFICATION_NOT_FOUND")
    assert_error(await client.post(f"{N}/{uuid.uuid4()}/read", headers=a["h"]), 404, "NOTIFICATION_NOT_FOUND")
    assert_error(await client.post(f"{N}/nope/read", headers=a["h"]), 422, "VALIDATION_ERROR")
    assert_error(await client.post(f"{N}/{nid}/read"), 401, "UNAUTHORIZED")
    assert (await client.get(f"{N}/unread-count", headers=a["h"])).json() == {"unread": 1}, (
        "b's attempt changed nothing"
    )


async def test_application_events_reach_the_right_inboxes(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    job = await create_job(client, rec, publish=True)
    await sql("DELETE FROM notifications")
    app = await apply_job(client, cand, job["id"])
    mine = (await client.get(N, headers=cand["h"])).json()["items"]
    assert [(n["type"], n["title"]) for n in mine] == [("APPLICATION_SUBMITTED", "Application submitted")]
    assert mine[0]["application_id"] == app["id"] and mine[0]["job_id"] == job["id"]
    theirs = (await client.get(N, headers=rec["h"])).json()["items"]
    assert [n["title"] for n in theirs if n["type"] == "APPLICATION_SUBMITTED"] == ["New application"]
    assert "Casey Candidate" in next(n["message"] for n in theirs if n["type"] == "APPLICATION_SUBMITTED")


# --- staging (service level) ---------------------------------------------------------------------------------------------------------------------------------


async def test_staging_the_same_event_twice_creates_one_notification(session: Any) -> None:
    from app.core.security import Role
    from app.db.models import User

    user = User(
        email="stage@test.example", password_hash="x", first_name="S", last_name="T", role=Role.CANDIDATE
    )
    session.add(user)
    await session.flush()
    svc = NotificationService(session)
    for _ in range(3):
        await svc.stage(
            user.id, NotificationType.APPLICATION_SUBMITTED, "Title", "Message", dedupe_key="evt-1"
        )
    await svc.stage(user.id, NotificationType.APPLICATION_SUBMITTED, "Title", "Message", dedupe_key="evt-2")
    await session.commit()
    assert await scalar("SELECT count(*) FROM notifications WHERE user_id = :u", u=user.id) == 2


async def test_dedupe_keys_are_scoped_per_user_and_null_keys_never_collide(session: Any) -> None:
    from app.core.security import Role
    from app.db.models import User

    users = [
        User(
            email=f"u{i}@test.example", password_hash="x", first_name="S", last_name="T", role=Role.CANDIDATE
        )
        for i in range(2)
    ]
    session.add_all(users)
    await session.flush()
    svc = NotificationService(session)
    for u in users:
        await svc.stage(u.id, NotificationType.NEW_JOB_RECOMMENDATION, "T", "M", dedupe_key="shared")
    for _ in range(3):
        await svc.stage(
            users[0].id, NotificationType.NEW_JOB_RECOMMENDATION, "T", "M"
        )  # no key: always inserted
    await session.commit()
    assert await scalar("SELECT count(*) FROM notifications WHERE dedupe_key = 'shared'") == 2
    assert await scalar("SELECT count(*) FROM notifications WHERE dedupe_key IS NULL") == 3


async def test_staging_truncates_oversized_text(session: Any) -> None:
    from app.core.security import Role
    from app.db.models import User

    user = User(
        email="long@test.example", password_hash="x", first_name="S", last_name="T", role=Role.CANDIDATE
    )
    session.add(user)
    await session.flush()
    await NotificationService(session).stage(user.id, NotificationType.RESUME_FAILED, "t" * 500, "m" * 5000)
    await session.commit()
    row = (
        await sql("SELECT length(title), length(message) FROM notifications WHERE user_id = :u", u=user.id)
    )[0]
    assert tuple(row) == (200, 1000)


async def test_a_deleted_user_takes_their_notifications_with_them(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    await seed(cand["user"]["id"], 2)
    await sql("DELETE FROM users WHERE id = :u", u=uuid.UUID(cand["user"]["id"]))
    assert (
        await scalar("SELECT count(*) FROM notifications WHERE user_id = :u", u=uuid.UUID(cand["user"]["id"]))
        == 0
    )
