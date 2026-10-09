"""Platform user administration, companies (tenants) and their members."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import (
    PASSWORD,
    add_staff,
    create_admin,
    create_job,
    register_candidate,
    register_employer,
    unique_email,
)
from tests.helpers_spine import (  # noqa: F401
    API,
    assert_error,
    fast_argon,
    login,
    refresh,
    refresh_cookie,
    scalar,
    walk,
)

pytestmark = pytest.mark.e2e


def new_user(**overrides: Any) -> dict[str, Any]:
    return {
        "email": unique_email("adm"),
        "password": PASSWORD,
        "first_name": "New",
        "last_name": "User",
        "role": "CANDIDATE",
        **overrides,
    }


# --- admin user CRUD ----------------------------------------------------------------------------------------------------


async def test_admin_creates_users_of_every_role(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client)
    cases = [
        ("CANDIDATE", None),
        ("ADMIN", None),
        ("RECRUITER", rec["company_id"]),
        ("HIRING_MANAGER", rec["company_id"]),
    ]
    for role, company_id in cases:
        r = await client.post(
            f"{API}/users", headers=admin["h"], json=new_user(role=role, company_id=company_id)
        )
        assert r.status_code == 201, r.text
        user = r.json()
        assert user["role"] == role and user["company_id"] == company_id and user["status"] == "ACTIVE"
        assert "password" not in r.text and "hash" not in r.text
        assert (await login(client, user["email"])).status_code == 200
        profiles = await scalar(
            "SELECT count(*) FROM candidate_profiles WHERE user_id = :u", u=uuid.UUID(user["id"])
        )
        recruiter_rows = await scalar(
            "SELECT count(*) FROM recruiter_profiles WHERE user_id = :u", u=uuid.UUID(user["id"])
        )
        assert profiles == (1 if role == "CANDIDATE" else 0) and recruiter_rows == (1 if company_id else 0)
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'user.created'") == 4


async def test_admin_user_validation_and_conflicts(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client)
    existing = await client.post(f"{API}/users", headers=admin["h"], json=new_user())
    assert_error(
        await client.post(
            f"{API}/users", headers=admin["h"], json=new_user(email=existing.json()["email"].upper())
        ),
        409,
        "EMAIL_ALREADY_REGISTERED",
    )
    assert_error(
        await client.post(f"{API}/users", headers=admin["h"], json=new_user(password="weak")),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(f"{API}/users", headers=admin["h"], json=new_user(role="SUPERUSER")),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(f"{API}/users", headers=admin["h"], json=new_user(role="RECRUITER")),
        422,
        "COMPANY_REQUIRED",
    )
    assert_error(
        await client.post(f"{API}/users", headers=admin["h"], json=new_user(role="HIRING_MANAGER")),
        422,
        "COMPANY_REQUIRED",
    )
    assert_error(
        await client.post(
            f"{API}/users", headers=admin["h"], json=new_user(role="CANDIDATE", company_id=rec["company_id"])
        ),
        422,
        "COMPANY_NOT_ALLOWED",
    )
    assert_error(
        await client.post(
            f"{API}/users", headers=admin["h"], json=new_user(role="ADMIN", company_id=rec["company_id"])
        ),
        422,
        "COMPANY_NOT_ALLOWED",
    )
    assert_error(
        await client.post(
            f"{API}/users", headers=admin["h"], json=new_user(role="RECRUITER", company_id=str(uuid.uuid4()))
        ),
        404,
        "COMPANY_NOT_FOUND",
    )


async def test_admin_lists_filters_and_pages_users(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client, "Listing Co")
    await add_staff(client, rec, "HIRING_MANAGER")
    cands = [await register_candidate(client, first=f"Person{i}", last="Lister") for i in range(3)]
    base = await client.get(f"{API}/users", headers=admin["h"])
    assert base.status_code == 200
    body = base.json()
    assert (
        set(body) == {"items", "page", "page_size", "total", "pages"}
        and body["total"] == 6
        and body["pages"] == 1
    )
    assert not any(k in {"password", "password_hash"} for k, _ in walk(body))
    by_role = (await client.get(f"{API}/users", headers=admin["h"], params={"role": "CANDIDATE"})).json()
    assert by_role["total"] == 3 and {u["role"] for u in by_role["items"]} == {"CANDIDATE"}
    by_company = (
        await client.get(f"{API}/users", headers=admin["h"], params={"company_id": rec["company_id"]})
    ).json()
    assert by_company["total"] == 2
    by_q = (await client.get(f"{API}/users", headers=admin["h"], params={"q": "lister"})).json()
    assert by_q["total"] == 3
    by_email = (
        await client.get(f"{API}/users", headers=admin["h"], params={"q": cands[0]["email"][:12].upper()})
    ).json()
    assert by_email["total"] >= 1
    assert (await client.get(f"{API}/users", headers=admin["h"], params={"q": "%"})).json()["total"] == 0, (
        "wildcards are literals"
    )
    await client.patch(
        f"{API}/users/{cands[1]['user']['id']}", headers=admin["h"], json={"status": "SUSPENDED"}
    )
    assert (await client.get(f"{API}/users", headers=admin["h"], params={"status": "SUSPENDED"})).json()[
        "total"
    ] == 1
    page2 = (await client.get(f"{API}/users", headers=admin["h"], params={"page": 2, "page_size": 4})).json()
    assert page2["page"] == 2 and page2["pages"] == 2 and len(page2["items"]) == 2 and page2["total"] == 6
    ids = [
        u["id"]
        for p in (1, 2)
        for u in (
            await client.get(f"{API}/users", headers=admin["h"], params={"page": p, "page_size": 4})
        ).json()["items"]
    ]
    assert len(set(ids)) == 6, "pagination neither skips nor repeats rows"


async def test_admin_updates_a_user(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client)
    cand = await register_candidate(client)
    r = await client.patch(
        f"{API}/users/{cand['user']['id']}",
        headers=admin["h"],
        json={"first_name": "Renamed", "phone": "+49 30 123456"},
    )
    assert (
        r.status_code == 200 and r.json()["first_name"] == "Renamed" and r.json()["phone"] == "+49 30 123456"
    )
    # candidate -> recruiter requires a company; with one it works and the company_id sticks
    assert_error(
        await client.patch(
            f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"role": "RECRUITER"}
        ),
        422,
        "COMPANY_REQUIRED",
    )
    r = await client.patch(
        f"{API}/users/{cand['user']['id']}",
        headers=admin["h"],
        json={"role": "RECRUITER", "company_id": rec["company_id"]},
    )
    assert (
        r.status_code == 200
        and r.json()["role"] == "RECRUITER"
        and r.json()["company_id"] == rec["company_id"]
    )
    assert (
        await scalar(
            "SELECT count(*) FROM recruiter_profiles WHERE user_id = :u", u=uuid.UUID(cand["user"]["id"])
        )
        == 1
    )
    # staff -> non-staff drops the company
    r = await client.patch(f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"role": "ADMIN"})
    assert r.status_code == 200 and r.json()["company_id"] is None
    assert_error(await client.get(f"{API}/users/{uuid.uuid4()}", headers=admin["h"]), 404, "USER_NOT_FOUND")
    assert_error(
        await client.patch(f"{API}/users/{uuid.uuid4()}", headers=admin["h"], json={"first_name": "x"}),
        404,
        "USER_NOT_FOUND",
    )
    assert (await client.get(f"{API}/users/{cand['user']['id']}", headers=admin["h"])).json()[
        "role"
    ] == "ADMIN"


async def test_staff_must_belong_to_a_company_when_updating(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client)
    # explicitly detaching a recruiter from their company is refused
    assert_error(
        await client.patch(f"{API}/users/{rec['user']['id']}", headers=admin["h"], json={"company_id": None}),
        422,
        "COMPANY_REQUIRED",
    )
    # moving to another company is allowed
    other = await register_employer(client)
    r = await client.patch(
        f"{API}/users/{rec['user']['id']}", headers=admin["h"], json={"company_id": other["company_id"]}
    )
    assert r.status_code == 200 and r.json()["company_id"] == other["company_id"]


async def test_admin_cannot_suspend_or_demote_themselves(client: AsyncClient) -> None:
    admin = await create_admin(client)
    me = admin["user"]["id"]
    assert_error(
        await client.patch(f"{API}/users/{me}", headers=admin["h"], json={"status": "SUSPENDED"}),
        422,
        "SELF_MODIFICATION",
    )
    assert_error(
        await client.patch(f"{API}/users/{me}", headers=admin["h"], json={"role": "CANDIDATE"}),
        422,
        "SELF_MODIFICATION",
    )
    assert (
        await client.patch(
            f"{API}/users/{me}", headers=admin["h"], json={"role": "ADMIN", "first_name": "Still"}
        )
    ).status_code == 200
    assert (await client.get(f"{API}/auth/me", headers=admin["h"])).json()["role"] == "ADMIN"


async def test_suspending_a_user_revokes_their_sessions_and_audits_it(client: AsyncClient) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    cookie = refresh_cookie(await login(client, cand["email"]))
    await client.patch(f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"status": "SUSPENDED"})
    assert_error(await refresh(client, cookie), 401)
    assert (
        await scalar(
            "SELECT count(*) FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL",
            u=uuid.UUID(cand["user"]["id"]),
        )
        == 0
    )
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'user.updated'") == 1


@pytest.mark.parametrize("role", ["recruiter", "hiring_manager", "candidate"])
async def test_user_administration_is_admin_only(client: AsyncClient, role: str) -> None:
    rec = await register_employer(client)
    actor = {
        "recruiter": rec,
        "hiring_manager": await add_staff(client, rec, "HIRING_MANAGER"),
        "candidate": await register_candidate(client),
    }[role]
    target = actor["user"]["id"]
    for method, url, body in (
        ("GET", f"{API}/users", None),
        ("POST", f"{API}/users", new_user()),
        ("GET", f"{API}/users/{target}", None),
        ("PATCH", f"{API}/users/{target}", {"first_name": "x"}),
    ):
        r = await client.request(method, url, headers=actor["h"], json=body)
        assert_error(r, 403, "FORBIDDEN")
    for method, url in (("GET", f"{API}/users"), ("GET", f"{API}/users/{target}")):
        assert_error(await client.request(method, url), 401, "UNAUTHORIZED")


# --- companies ------------------------------------------------------------------------------------------------------------------------------


async def test_public_company_profile_exposes_only_public_fields(client: AsyncClient) -> None:
    rec = await register_employer(client, "Public Corp")
    r = await client.get(f"{API}/companies/{rec['company_id']}")  # no authentication
    assert r.status_code == 200
    assert set(r.json()) == {
        "id",
        "name",
        "slug",
        "description",
        "industry",
        "website",
        "location",
        "size",
        "logo_url",
    }
    assert r.json()["name"] == "Public Corp"
    assert rec["email"] not in r.text and rec["user"]["id"] not in r.text
    assert_error(await client.get(f"{API}/companies/{uuid.uuid4()}"), 404, "COMPANY_NOT_FOUND")
    assert_error(await client.get(f"{API}/companies/not-a-uuid"), 422, "VALIDATION_ERROR")


async def test_my_company(client: AsyncClient) -> None:
    rec = await register_employer(client, "Mine Inc")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    for acct in (rec, hm):
        r = await client.get(f"{API}/companies/me", headers=acct["h"])
        assert r.status_code == 200 and r.json()["name"] == "Mine Inc" and r.json()["status"] == "ACTIVE"
        assert {"status", "created_at", "updated_at"} <= set(r.json())
    cand = await register_candidate(client)
    assert_error(await client.get(f"{API}/companies/me", headers=cand["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(f"{API}/companies/me"), 401, "UNAUTHORIZED")


async def test_admin_company_list_and_create(client: AsyncClient) -> None:
    admin = await create_admin(client)
    for name in ("Alpha Works", "Beta Works", "Gamma Labs"):
        await register_employer(client, name)
    r = await client.get(f"{API}/companies", headers=admin["h"], params={"q": "works"})
    assert r.status_code == 200 and [c["name"] for c in r.json()["items"]] == ["Alpha Works", "Beta Works"]
    assert (await client.get(f"{API}/companies", headers=admin["h"], params={"q": "%"})).json()["total"] == 0
    created = await client.post(
        f"{API}/companies",
        headers=admin["h"],
        json={"name": "Delta Corp", "industry": "Mining", "website": "https://delta.example.com"},
    )
    assert (
        created.status_code == 201
        and created.json()["slug"] == "delta-corp"
        and created.json()["status"] == "ACTIVE"
    )
    assert_error(
        await client.post(f"{API}/companies", headers=admin["h"], json={"name": "DELTA corp"}),
        409,
        "COMPANY_NAME_TAKEN",
    )
    assert_error(
        await client.post(
            f"{API}/companies",
            headers=admin["h"],
            json={"name": "Bad Site", "website": "javascript:alert(1)"},
        ),
        422,
        "VALIDATION_ERROR",
    )
    rec = await register_employer(client)
    assert_error(await client.get(f"{API}/companies", headers=rec["h"]), 403, "FORBIDDEN")
    assert_error(
        await client.post(f"{API}/companies", headers=rec["h"], json={"name": "Nope Corp"}), 403, "FORBIDDEN"
    )
    suspended = await client.patch(
        f"{API}/companies/{created.json()['id']}", headers=admin["h"], json={"status": "SUSPENDED"}
    )
    assert suspended.status_code == 200
    assert [
        c["name"]
        for c in (
            await client.get(f"{API}/companies", headers=admin["h"], params={"status": "SUSPENDED"})
        ).json()["items"]
    ] == ["Delta Corp"]


async def test_company_updates_by_its_administrator(client: AsyncClient) -> None:
    team = {"rec": await register_employer(client, "Editable Co")}
    rec = team["rec"]
    r = await client.patch(
        f"{API}/companies/{rec['company_id']}",
        headers=rec["h"],
        json={
            "description": "We build things.",
            "industry": "Manufacturing",
            "website": "https://editable.example.com",
            "size": "51-200",
            "location": "Oslo",
        },
    )
    assert r.status_code == 200, r.text
    assert (r.json()["description"], r.json()["size"], r.json()["location"]) == (
        "We build things.",
        "51-200",
        "Oslo",
    )
    public = (await client.get(f"{API}/companies/{rec['company_id']}")).json()
    assert public["website"] == "https://editable.example.com" and public["industry"] == "Manufacturing"
    assert (
        await client.patch(
            f"{API}/companies/{rec['company_id']}", headers=rec["h"], json={"name": "EDITABLE CO"}
        )
    ).status_code == 200  # case-only rename of itself
    assert_error(
        await client.patch(
            f"{API}/companies/{rec['company_id']}", headers=rec["h"], json={"website": "not a url"}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert (
        await client.patch(
            f"{API}/companies/{rec['company_id']}", headers=rec["h"], json={"name": None, "description": None}
        )
    ).json()["name"] == "EDITABLE CO"
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'company.updated'") == 3


async def test_company_name_uniqueness_on_update(client: AsyncClient) -> None:
    a = await register_employer(client, "Taken Name Ltd")
    b = await register_employer(client, "Other Name Ltd")
    assert_error(
        await client.patch(
            f"{API}/companies/{b['company_id']}", headers=b["h"], json={"name": "taken name ltd"}
        ),
        409,
        "COMPANY_NAME_TAKEN",
    )
    assert (await client.get(f"{API}/companies/{b['company_id']}")).json()["name"] == "Other Name Ltd"
    assert a["company_id"] != b["company_id"]


async def test_company_update_authorization(client: AsyncClient) -> None:
    rec = await register_employer(client, "Guarded Co")
    plain_recruiter = await add_staff(
        client, rec, "RECRUITER"
    )  # a recruiter who is not a company administrator
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    outsider = await register_employer(client, "Outsider Co")
    cand = await register_candidate(client)
    admin = await create_admin(client)
    url = f"{API}/companies/{rec['company_id']}"
    body = {"description": "changed"}
    assert_error(await client.patch(url, headers=plain_recruiter["h"], json=body), 403, "FORBIDDEN")
    assert_error(await client.patch(url, headers=hm["h"], json=body), 403, "FORBIDDEN")
    assert_error(await client.patch(url, headers=cand["h"], json=body), 403, "FORBIDDEN")
    assert_error(
        await client.patch(url, headers=outsider["h"], json=body), 404, "COMPANY_NOT_FOUND"
    )  # another tenant: not even visible
    assert_error(await client.patch(url, json=body), 401, "UNAUTHORIZED")
    assert (await client.patch(url, headers=admin["h"], json=body)).status_code == 200
    # status is reserved for platform administrators
    assert_error(await client.patch(url, headers=rec["h"], json={"status": "SUSPENDED"}), 403, "FORBIDDEN")
    assert (await client.patch(url, headers=admin["h"], json={"status": "SUSPENDED"})).json()[
        "status"
    ] == "SUSPENDED"


async def test_suspended_company_cannot_create_or_publish_jobs(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client, "Soon Suspended")
    draft = await create_job(client, rec)
    live = await create_job(client, rec, publish=True, title="Already Live Engineer")
    await client.patch(
        f"{API}/companies/{rec['company_id']}", headers=admin["h"], json={"status": "SUSPENDED"}
    )
    from tests.helpers import job_payload

    assert_error(
        await client.post(f"{API}/jobs", headers=rec["h"], json=job_payload("Brand New Role")),
        422,
        "COMPANY_SUSPENDED",
    )
    err = assert_error(
        await client.post(f"{API}/jobs/{draft['id']}/publish", headers=rec["h"]),
        422,
        "PUBLISH_VALIDATION_FAILED",
    )
    assert any("suspended" in d.lower() for d in err["details"])
    assert (await client.get(f"{API}/jobs/{draft['id']}", headers=rec["h"])).json()["status"] == "DRAFT"
    # reactivation restores the ability to publish
    await client.patch(f"{API}/companies/{rec['company_id']}", headers=admin["h"], json={"status": "ACTIVE"})
    assert (await client.post(f"{API}/jobs/{draft['id']}/publish", headers=rec["h"])).status_code == 200
    assert live["id"]


# --- members ------------------------------------------------------------------------------------------------------------------------------------


async def test_member_list_is_scoped_to_the_tenant(client: AsyncClient) -> None:
    rec = await register_employer(client, "Team Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    rec2 = await add_staff(client, rec, "RECRUITER")
    outsider = await register_employer(client, "Rival Co")
    cand = await register_candidate(client)
    admin = await create_admin(client)
    url = f"{API}/companies/{rec['company_id']}/members"
    for viewer in (rec, hm, rec2, admin):
        r = await client.get(url, headers=viewer["h"])
        assert r.status_code == 200, (viewer["user"]["role"], r.text)
        assert {m["email"] for m in r.json()} == {rec["email"], hm["email"], rec2["email"]}
        assert {m["id"] for m in r.json()} == {rec["user"]["id"], hm["user"]["id"], rec2["user"]["id"]}
    members = {m["email"]: m for m in (await client.get(url, headers=rec["h"])).json()}
    assert (
        members[rec["email"]]["is_company_admin"] is True
        and members[hm["email"]]["is_company_admin"] is False
    )
    assert members[hm["email"]]["role"] == "HIRING_MANAGER"
    assert set(members[hm["email"]]) == {
        "id",
        "email",
        "first_name",
        "last_name",
        "role",
        "status",
        "job_title",
        "department",
        "is_company_admin",
        "last_login_at",
    }
    for stranger in (outsider, cand):
        assert_error(await client.get(url, headers=stranger["h"]), 404, "COMPANY_NOT_FOUND")
    assert_error(await client.get(url), 401, "UNAUTHORIZED")
    assert (
        len(
            (
                await client.get(f"{API}/companies/{outsider['company_id']}/members", headers=outsider["h"])
            ).json()
        )
        == 1
    )


async def test_only_company_administrators_can_add_members(client: AsyncClient) -> None:
    rec = await register_employer(client, "Hiring Co")
    plain = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    outsider = await register_employer(client, "Else Co")
    cand = await register_candidate(client)
    url = f"{API}/companies/{rec['company_id']}/members"

    def body(**o: Any) -> dict[str, Any]:
        return {
            "email": unique_email("m"),
            "password": PASSWORD,
            "first_name": "Mem",
            "last_name": "Ber",
            "role": "HIRING_MANAGER",
            **o,
        }

    for actor in (plain, hm, outsider, cand):
        assert_error(await client.post(url, headers=actor["h"], json=body()), 403, "FORBIDDEN")
    assert_error(await client.post(url, json=body()), 401, "UNAUTHORIZED")
    r = await client.post(url, headers=rec["h"], json=body(job_title="Engineering Manager", department="R&D"))
    assert r.status_code == 201, r.text
    member = r.json()
    assert (
        member["role"],
        member["job_title"],
        member["department"],
        member["is_company_admin"],
        member["status"],
    ) == ("HIRING_MANAGER", "Engineering Manager", "R&D", False, "ACTIVE")
    assert (await login(client, member["email"])).json()["user"]["company_id"] == rec["company_id"]
    assert_error(
        await client.post(f"{API}/companies/{uuid.uuid4()}/members", headers=rec["h"], json=body()),
        404,
        "COMPANY_NOT_FOUND",
    )


async def test_member_creation_validation(client: AsyncClient) -> None:
    rec = await register_employer(client)
    url = f"{API}/companies/{rec['company_id']}/members"
    base = {"email": unique_email("v"), "password": PASSWORD, "first_name": "A", "last_name": "B"}
    for role in ("ADMIN", "CANDIDATE", "SUPERUSER"):
        assert_error(
            await client.post(url, headers=rec["h"], json={**base, "role": role}), 422, "VALIDATION_ERROR"
        )
    assert_error(
        await client.post(url, headers=rec["h"], json={**base, "password": "weak"}), 422, "VALIDATION_ERROR"
    )
    assert_error(
        await client.post(url, headers=rec["h"], json={**base, "email": rec["email"].upper()}),
        409,
        "EMAIL_ALREADY_REGISTERED",
    )
    ok = await client.post(url, headers=rec["h"], json=base)  # role defaults to RECRUITER
    assert ok.status_code == 201 and ok.json()["role"] == "RECRUITER"


async def test_member_updates(client: AsyncClient) -> None:
    rec = await register_employer(client, "Update Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    plain = await add_staff(client, rec, "RECRUITER")
    outsider = await register_employer(client, "Foreign Co")
    base = f"{API}/companies/{rec['company_id']}/members"
    r = await client.patch(
        f"{base}/{hm['user']['id']}",
        headers=rec["h"],
        json={"role": "RECRUITER", "job_title": "Lead", "department": "People"},
    )
    assert r.status_code == 200 and (r.json()["role"], r.json()["job_title"], r.json()["department"]) == (
        "RECRUITER",
        "Lead",
        "People",
    )
    # the promotion is live immediately: the (still valid) token's *database* role decides
    assert (await client.get(f"{API}/auth/me", headers=hm["h"])).json()["role"] == "RECRUITER"
    # authorization
    assert_error(
        await client.patch(f"{base}/{hm['user']['id']}", headers=plain["h"], json={"job_title": "x"}),
        403,
        "FORBIDDEN",
    )
    assert_error(
        await client.patch(f"{base}/{hm['user']['id']}", headers=outsider["h"], json={"job_title": "x"}),
        403,
        "FORBIDDEN",
    )
    assert_error(
        await client.patch(f"{base}/{outsider['user']['id']}", headers=rec["h"], json={"job_title": "x"}),
        404,
        "MEMBER_NOT_FOUND",
    )
    assert_error(
        await client.patch(f"{base}/{uuid.uuid4()}", headers=rec["h"], json={"job_title": "x"}),
        404,
        "MEMBER_NOT_FOUND",
    )
    assert_error(
        await client.patch(f"{base}/{hm['user']['id']}", headers=rec["h"], json={"role": "ADMIN"}),
        422,
        "VALIDATION_ERROR",
    )
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'member.updated'") == 1


async def test_member_suspension_blocks_the_member_but_not_themselves(client: AsyncClient) -> None:
    rec = await register_employer(client, "Suspend Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    base = f"{API}/companies/{rec['company_id']}/members"
    assert_error(
        await client.patch(f"{base}/{rec['user']['id']}", headers=rec["h"], json={"status": "SUSPENDED"}),
        422,
        "SELF_MODIFICATION",
    )
    assert_error(
        await client.patch(f"{base}/{rec['user']['id']}", headers=rec["h"], json={"role": "HIRING_MANAGER"}),
        422,
        "SELF_MODIFICATION",
    )
    cookie = refresh_cookie(await login(client, hm["email"]))
    r = await client.patch(f"{base}/{hm['user']['id']}", headers=rec["h"], json={"status": "SUSPENDED"})
    assert r.status_code == 200 and r.json()["status"] == "SUSPENDED"
    assert_error(await client.get(f"{API}/auth/me", headers=hm["h"]), 401, "ACCOUNT_SUSPENDED")
    assert_error(await login(client, hm["email"]), 401, "ACCOUNT_SUSPENDED")
    assert_error(await refresh(client, cookie), 401)
    assert (
        await client.patch(f"{base}/{hm['user']['id']}", headers=rec["h"], json={"status": "ACTIVE"})
    ).status_code == 200
    assert (await login(client, hm["email"])).status_code == 200


async def test_suspended_company_postings_leave_the_public_site_and_return_on_reactivation(
    client: AsyncClient,
) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client, "Vanishing Co")
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    jobs_url = f"{API}/search/jobs"
    assert (await client.get(jobs_url)).json()["total"] == 1
    await client.patch(
        f"{API}/companies/{rec['company_id']}", headers=admin["h"], json={"status": "SUSPENDED"}
    )
    assert (await client.get(jobs_url)).json()["total"] == 0
    assert_error(await client.get(f"{API}/jobs/{job['id']}"), 404, "JOB_NOT_FOUND")
    assert_error(await client.get(f"{API}/jobs/{job['id']}", headers=cand["h"]), 404, "JOB_NOT_FOUND")
    assert_error(
        await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job["id"]}),
        404,
        "JOB_NOT_FOUND",
    )
    assert_error(await client.put(f"{API}/jobs/{job['id']}/save", headers=cand["h"]), 404, "JOB_NOT_FOUND")
    assert (
        await client.get(f"{API}/jobs/{job['id']}", headers=rec["h"])
    ).status_code == 200  # the company itself still sees it
    await client.patch(f"{API}/companies/{rec['company_id']}", headers=admin["h"], json={"status": "ACTIVE"})
    assert (await client.get(jobs_url)).json()["total"] == 1
    assert (
        await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job["id"]})
    ).status_code == 201
