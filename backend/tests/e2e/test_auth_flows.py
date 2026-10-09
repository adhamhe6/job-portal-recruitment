"""Authentication: registration, login, refresh rotation, logout, password change, token handling, rate limits."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import ROLE_PERMISSIONS, Role, create_access_token
from tests.helpers import (
    PASSWORD,
    add_staff,
    auth,
    create_admin,
    register_candidate,
    register_employer,
    unique_email,
)
from tests.helpers_spine import (  # noqa: F401
    API,
    assert_error,
    client_from,
    fast_argon,
    login,
    refresh,
    refresh_cookie,
    scalar,
    set_cookie_headers,
    sql,
    walk,
)

pytestmark = pytest.mark.e2e

REG = f"{API}/auth/register"
REG_EMP = f"{API}/auth/register/employer"


def candidate_body(**overrides: object) -> dict[str, object]:
    return {
        "email": unique_email("reg"),
        "password": PASSWORD,
        "first_name": "Ada",
        "last_name": "Lovelace",
        **overrides,
    }


def employer_body(**overrides: object) -> dict[str, object]:
    return {
        **candidate_body(),
        "company_name": f"Acme {uuid.uuid4().hex[:6]}",
        "company_industry": "Software",
        **overrides,
    }


# --- registration ----------------------------------------------------------------------------------------------------


async def test_register_candidate_response_shape(client: AsyncClient) -> None:
    r = await client.post(REG, json=candidate_body(email="Ada.Lovelace@Example.COM"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert (
        body["token_type"] == "bearer"
        and body["expires_in"] == get_settings().access_token_expire_minutes * 60
    )
    user = body["user"]
    assert user["email"] == "ada.lovelace@example.com"  # stored lower-cased
    assert (
        user["role"] == "CANDIDATE"
        and user["status"] == "ACTIVE"
        and user["company"] is None
        and user["company_id"] is None
    )
    assert user["candidate_id"] and user["is_company_admin"] is False
    assert user["permissions"] == sorted(p.value for p in ROLE_PERMISSIONS[Role.CANDIDATE])
    assert refresh_cookie(r)
    # a profile and an audit event exist
    assert (
        await scalar("SELECT count(*) FROM candidate_profiles WHERE user_id = :u", u=uuid.UUID(user["id"]))
        == 1
    )
    assert (
        await scalar(
            "SELECT count(*) FROM audit_events WHERE action = 'user.registered' AND actor_id = :u",
            u=uuid.UUID(user["id"]),
        )
        == 1
    )
    # the registration response logs the user in
    assert (await client.get(f"{API}/auth/me", headers=auth(body["access_token"]))).json()["id"] == user["id"]


async def test_register_ignores_attempts_to_choose_a_role_or_status(client: AsyncClient) -> None:
    r = await client.post(
        REG,
        json=candidate_body(
            role="ADMIN", status="SUSPENDED", company_id=str(uuid.uuid4()), is_company_admin=True
        ),
    )
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["role"] == "CANDIDATE" and user["status"] == "ACTIVE" and user["company_id"] is None
    r = await client.post(REG_EMP, json=employer_body(role="ADMIN"))
    assert r.status_code == 201 and r.json()["user"]["role"] == "RECRUITER"


async def test_register_employer_creates_company_and_company_admin(client: AsyncClient) -> None:
    r = await client.post(
        REG_EMP,
        json=employer_body(company_name="Acme Robotics", company_size="11-50", job_title="Head of Talent"),
    )
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["role"] == "RECRUITER" and user["is_company_admin"] is True and user["candidate_id"] is None
    assert user["company"]["name"] == "Acme Robotics" and user["company"]["slug"] == "acme-robotics"
    assert user["permissions"] == sorted(p.value for p in ROLE_PERMISSIONS[Role.RECRUITER])
    company = (await client.get(f"{API}/companies/{user['company_id']}")).json()
    assert company["size"] == "11-50" and company["name"] == "Acme Robotics"
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'company.created'") == 1


async def test_duplicate_email_is_rejected_case_insensitively(client: AsyncClient) -> None:
    first = await client.post(REG, json=candidate_body(email="Ada@Example.com"))
    assert first.status_code == 201
    for variant in ("ada@example.com", "ADA@EXAMPLE.COM", "aDa@Example.Com"):
        r = await client.post(REG, json=candidate_body(email=variant))
        assert_error(r, 409, "EMAIL_ALREADY_REGISTERED")
    # also across account types
    assert_error(
        await client.post(REG_EMP, json=employer_body(email="ADA@example.com")),
        409,
        "EMAIL_ALREADY_REGISTERED",
    )
    assert await scalar("SELECT count(*) FROM users") == 1


async def test_duplicate_company_name_is_rejected_case_insensitively(client: AsyncClient) -> None:
    assert (await client.post(REG_EMP, json=employer_body(company_name="Globex Corp"))).status_code == 201
    for name in ("Globex Corp", "globex corp", "GLOBEX CORP"):
        assert_error(
            await client.post(REG_EMP, json=employer_body(company_name=name)), 409, "COMPANY_NAME_TAKEN"
        )
    assert await scalar("SELECT count(*) FROM companies") == 1
    assert await scalar("SELECT count(*) FROM users") == 1, (
        "a failed employer registration must not leave a user behind"
    )


async def test_company_slugs_stay_unique_when_names_collide_after_slugging(client: AsyncClient) -> None:
    slugs = []
    for name in ("Acme Inc", "Acme-Inc", "ACME  inc!"):
        r = await client.post(REG_EMP, json=employer_body(company_name=name))
        assert r.status_code == 201, r.text
        slugs.append(r.json()["user"]["company"]["slug"])
    assert slugs == ["acme-inc", "acme-inc-2", "acme-inc-3"]


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short1", "at least 10"),
        ("nodigitsatall", "letter and one digit"),
        ("1234567890123", "letter and one digit"),
        ("a1" * 70, "at most 128"),
    ],
)
async def test_weak_passwords_get_field_level_details(
    client: AsyncClient, password: str, fragment: str
) -> None:
    err = assert_error(
        await client.post(REG, json=candidate_body(password=password)), 422, "VALIDATION_ERROR"
    )
    detail = next(d for d in err["details"] if d["field"] == "password")
    assert fragment in detail["message"] and detail["type"] == "value_error"
    assert password not in json.dumps(err), "the rejected password must not be echoed back"


async def test_validation_errors_list_every_bad_field(client: AsyncClient) -> None:
    err = assert_error(
        await client.post(
            REG, json={"email": "not-an-email", "password": "x", "first_name": "", "phone": "abc"}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert {d["field"] for d in err["details"]} >= {"email", "password", "first_name", "last_name", "phone"}
    assert_error(
        await client.post(REG, content=b"{not json", headers={"content-type": "application/json"}),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(await client.post(REG, json=[1, 2, 3]), 422, "VALIDATION_ERROR")


async def test_registration_response_never_contains_secrets(client: AsyncClient) -> None:
    r = await client.post(REG, json=candidate_body())
    text = r.text.lower()
    assert PASSWORD.lower() not in text and "argon2" not in text
    assert not any("password" in k or "hash" in k for k, _ in walk(r.json()))


# --- login ------------------------------------------------------------------------------------------------------------------


async def test_login_success_updates_last_login_and_sets_cookie(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    assert (
        await scalar("SELECT last_login_at FROM users WHERE email = :e", e=cand["email"]) is not None
    )  # registration logs in
    await sql("UPDATE users SET last_login_at = NULL WHERE email = :e", e=cand["email"])
    r = await login(client, cand["email"].upper())  # e-mail comparison is case-insensitive
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == cand["user"]["id"] and refresh_cookie(r)
    assert await scalar("SELECT last_login_at FROM users WHERE email = :e", e=cand["email"]) is not None
    assert (await client.get(f"{API}/auth/me", headers=auth(r.json()["access_token"]))).status_code == 200


async def test_wrong_password_and_unknown_email_are_indistinguishable(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    wrong = await login(client, cand["email"], "WrongPassword99")
    unknown = await login(client, "nobody@nowhere.example", PASSWORD)
    e1, e2 = (
        assert_error(wrong, 401, "INVALID_CREDENTIALS"),
        assert_error(unknown, 401, "INVALID_CREDENTIALS"),
    )
    assert e1["message"] == e2["message"] and e1["details"] == e2["details"] == None  # noqa: E711
    assert wrong.headers["www-authenticate"] == unknown.headers["www-authenticate"] == "Bearer"
    assert not set_cookie_headers(wrong) and not set_cookie_headers(unknown)


async def test_suspended_account_cannot_log_in_but_only_after_proving_the_password(
    client: AsyncClient,
) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    r = await client.patch(
        f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"status": "SUSPENDED"}
    )
    assert r.status_code == 200 and r.json()["status"] == "SUSPENDED"
    assert_error(await login(client, cand["email"]), 401, "ACCOUNT_SUSPENDED")
    # a wrong password must not reveal that the account is suspended
    assert_error(await login(client, cand["email"], "WrongPassword99"), 401, "INVALID_CREDENTIALS")
    await client.patch(f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"status": "ACTIVE"})
    assert (await login(client, cand["email"])).status_code == 200


async def test_suspension_takes_effect_immediately_for_tokens_already_issued(client: AsyncClient) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    sess = await login(client, cand["email"])
    token, cookie = sess.json()["access_token"], refresh_cookie(sess)
    assert (await client.get(f"{API}/auth/me", headers=auth(token))).status_code == 200
    assert (
        await client.patch(
            f"{API}/users/{cand['user']['id']}", headers=admin["h"], json={"status": "SUSPENDED"}
        )
    ).status_code == 200
    assert_error(await client.get(f"{API}/auth/me", headers=auth(token)), 401, "ACCOUNT_SUSPENDED")
    assert_error(await client.get(f"{API}/candidates/me", headers=auth(token)), 401, "ACCOUNT_SUSPENDED")
    assert_error(await refresh(client, cookie), 401)  # the refresh token was revoked too
    assert_error(
        await client.get(f"{API}/jobs/{uuid.uuid4()}", headers=auth(token)), 401, "ACCOUNT_SUSPENDED"
    )  # even on public routes


async def test_login_validation(client: AsyncClient) -> None:
    assert_error(
        await client.post(f"{API}/auth/login", json={"email": "bad", "password": "x"}),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(f"{API}/auth/login", json={"email": "a@example.com"}), 422, "VALIDATION_ERROR"
    )
    assert_error(
        await client.post(f"{API}/auth/login", json={"email": "a@example.com", "password": ""}),
        422,
        "VALIDATION_ERROR",
    )


async def test_oauth2_password_form_login(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.post(f"{API}/auth/token", data={"username": cand["email"], "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["id"] == cand["user"]["id"] and refresh_cookie(r)
    assert (await client.get(f"{API}/auth/me", headers=auth(body["access_token"]))).status_code == 200
    bad = await client.post(
        f"{API}/auth/token", data={"username": cand["email"], "password": "WrongPassword99"}
    )
    assert_error(bad, 401, "INVALID_CREDENTIALS")
    assert_error(
        await client.post(f"{API}/auth/token", data={"username": cand["email"]}), 422, "VALIDATION_ERROR"
    )


# --- refresh cookie + rotation ----------------------------------------------------------------------------------------------------


async def test_refresh_cookie_flags(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cand = await register_candidate(client)
    r = await login(client, cand["email"])
    [header] = set_cookie_headers(r)
    attrs = [a.strip().lower() for a in header.split(";")]
    assert attrs[0].startswith("tl_refresh=") and "httponly" in attrs and "samesite=strict" in attrs
    assert (
        "path=/api/v1/auth" in attrs
        and f"max-age={get_settings().refresh_token_expire_days * 86400}" in attrs
    )
    assert "secure" not in attrs  # development default; production validation forces it on (see test_config)
    assert header.split(";", 1)[0].split("=", 1)[1] not in r.text, (
        "the refresh token must never be in the JSON body"
    )
    monkeypatch.setattr(get_settings(), "refresh_cookie_secure", True)
    r2 = await login(client, cand["email"])
    assert "secure" in [a.strip().lower() for a in set_cookie_headers(r2)[0].split(";")]


async def test_refresh_rotates_the_token_and_issues_a_new_access_token(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r1 = await login(client, cand["email"])
    t1 = refresh_cookie(r1)
    r2 = await refresh(client, t1)
    assert r2.status_code == 200, r2.text
    t2 = refresh_cookie(r2)
    assert t2 != t1 and r2.json()["access_token"] != r1.json()["access_token"]
    assert r2.json()["user"]["id"] == cand["user"]["id"]
    assert (await client.get(f"{API}/auth/me", headers=auth(r2.json()["access_token"]))).status_code == 200
    # one family, two rows, the first revoked
    rows = await sql(
        "SELECT family_id, revoked_at IS NOT NULL FROM refresh_tokens WHERE user_id = :u ORDER BY created_at",
        u=uuid.UUID(cand["user"]["id"]),
    )
    login_rows = rows[-2:]
    assert login_rows[0][0] == login_rows[1][0] and [r[1] for r in login_rows] == [True, False]
    # rotation chains
    r3 = await refresh(client, t2)
    assert r3.status_code == 200 and refresh_cookie(r3) not in (t1, t2)


async def test_refresh_tokens_are_stored_hashed(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    token = refresh_cookie(await login(client, cand["email"]))
    stored = [r[0] for r in await sql("SELECT token_hash FROM refresh_tokens")]
    assert token not in stored and all(len(h) == 64 for h in stored)


async def test_reuse_of_a_rotated_refresh_token_revokes_the_whole_family(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    t1 = refresh_cookie(await login(client, cand["email"]))
    other_session = refresh_cookie(await login(client, cand["email"]))  # an unrelated device
    t2 = refresh_cookie(await refresh(client, t1))
    t3 = refresh_cookie(await refresh(client, t2))
    # the attacker replays the long-gone t1 ...
    assert_error(await refresh(client, t1), 401, "INVALID_REFRESH_TOKEN")
    # ... and now even the legitimate newest token of that family is dead
    assert_error(await refresh(client, t3), 401, "INVALID_REFRESH_TOKEN")
    assert_error(await refresh(client, t2), 401, "INVALID_REFRESH_TOKEN")
    # other devices are unaffected
    assert (await refresh(client, other_session)).status_code == 200


@pytest.mark.parametrize("cookie", [None, "", "not-a-real-token", "x" * 64])
async def test_refresh_without_a_valid_cookie(client: AsyncClient, cookie: str | None) -> None:
    headers = {"Cookie": f"tl_refresh={cookie}"} if cookie is not None else {}
    r = await client.post(f"{API}/auth/refresh", headers=headers)
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")
    assert any(h.startswith("tl_refresh=") and "Max-Age=0" in h for h in set_cookie_headers(r)), (
        "the bad cookie is cleared"
    )


async def test_expired_refresh_token(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    token = refresh_cookie(await login(client, cand["email"]))
    await sql("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
    assert_error(await refresh(client, token), 401, "INVALID_REFRESH_TOKEN")


async def test_refresh_for_a_suspended_user_is_refused(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    token = refresh_cookie(await login(client, cand["email"]))
    await sql("UPDATE users SET status = 'SUSPENDED' WHERE email = :e", e=cand["email"])
    assert_error(await refresh(client, token), 401, "ACCOUNT_SUSPENDED")


async def test_refresh_tokens_cannot_be_used_as_bearer_tokens(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    token = refresh_cookie(await login(client, cand["email"]))
    assert_error(await client.get(f"{API}/auth/me", headers=auth(token)), 401, "INVALID_TOKEN")


# --- logout -------------------------------------------------------------------------------------------------------------------------


async def test_logout_revokes_the_refresh_token_and_denylists_the_access_token(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    sess = await login(client, cand["email"])
    token, cookie = sess.json()["access_token"], refresh_cookie(sess)
    r = await client.post(f"{API}/auth/logout", headers={**auth(token), "Cookie": f"tl_refresh={cookie}"})
    assert r.status_code == 200 and r.json() == {"message": "Signed out"}
    assert any("Max-Age=0" in h for h in set_cookie_headers(r))
    assert_error(await refresh(client, cookie), 401, "INVALID_REFRESH_TOKEN")
    assert_error(await client.get(f"{API}/auth/me", headers=auth(token)), 401, "TOKEN_REVOKED")
    # logging in again works and yields a different jti
    assert (await login(client, cand["email"])).status_code == 200


async def test_logout_only_revokes_its_own_session(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    a, b = await login(client, cand["email"]), await login(client, cand["email"])
    await client.post(
        f"{API}/auth/logout",
        headers={**auth(a.json()["access_token"]), "Cookie": f"tl_refresh={refresh_cookie(a)}"},
    )
    assert (await client.get(f"{API}/auth/me", headers=auth(b.json()["access_token"]))).status_code == 200
    assert (await refresh(client, refresh_cookie(b))).status_code == 200


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer garbage"}, {"Cookie": "tl_refresh=unknown"}]
)
async def test_logout_is_idempotent_and_tolerant(client: AsyncClient, headers: dict[str, str]) -> None:
    r = await client.post(f"{API}/auth/logout", headers=headers)
    assert r.status_code == 200 and r.json()["message"] == "Signed out"


# --- change password ---------------------------------------------------------------------------------------------------------------------------


async def test_change_password_revokes_every_session(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    a, b = await login(client, cand["email"]), await login(client, cand["email"])
    new_pw = "BrandNewPassw0rd"
    r = await client.post(
        f"{API}/auth/change-password",
        headers=auth(a.json()["access_token"]),
        json={"current_password": PASSWORD, "new_password": new_pw},
    )
    assert r.status_code == 200 and "sign in again" in r.json()["message"]
    assert any("Max-Age=0" in h for h in set_cookie_headers(r))
    for sess in (a, b):
        assert_error(await refresh(client, refresh_cookie(sess)), 401)
    assert_error(await login(client, cand["email"], PASSWORD), 401, "INVALID_CREDENTIALS")
    assert (await login(client, cand["email"], new_pw)).status_code == 200
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'user.password_changed'") == 1


async def test_change_password_validation(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    url = f"{API}/auth/change-password"
    assert_error(
        await client.post(
            url,
            headers=cand["h"],
            json={"current_password": "Wrong-password-1", "new_password": "BrandNewPassw0rd"},
        ),
        401,
        "INVALID_CREDENTIALS",
    )
    err = assert_error(
        await client.post(
            url, headers=cand["h"], json={"current_password": PASSWORD, "new_password": "weak"}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert err["details"][0]["field"] == "new_password"
    assert_error(
        await client.post(url, json={"current_password": PASSWORD, "new_password": "BrandNewPassw0rd"}),
        401,
        "UNAUTHORIZED",
    )
    assert (await login(client, cand["email"])).status_code == 200, (
        "a failed change must not alter the password"
    )


# --- /auth/me ----------------------------------------------------------------------------------------------------------------------------------------


async def test_me_for_every_role(client: AsyncClient) -> None:
    admin = await create_admin(client)
    rec = await register_employer(client, "Me Corp")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    for acct, role, company in (
        (admin, "ADMIN", False),
        (rec, "RECRUITER", True),
        (hm, "HIRING_MANAGER", True),
        (cand, "CANDIDATE", False),
    ):
        me = (await client.get(f"{API}/auth/me", headers=acct["h"])).json()
        assert me["role"] == role
        assert (me["company"] is not None) is company
        assert me["permissions"] == sorted(p.value for p in ROLE_PERMISSIONS[Role(role)])
        assert (me["candidate_id"] is not None) is (role == "CANDIDATE")
        assert me["is_company_admin"] is (role == "RECRUITER")
        assert set(me) >= {
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "status",
            "company_id",
            "last_login_at",
            "created_at",
            "company",
            "candidate_id",
            "is_company_admin",
            "permissions",
        }
        assert not any(k in me for k in ("password", "password_hash"))
    assert me["role"] == "CANDIDATE"


async def test_update_me_changes_names_and_syncs_the_candidate_profile(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.patch(
        f"{API}/auth/me",
        headers=cand["h"],
        json={"first_name": "  Grace ", "last_name": "Hopper", "phone": "+1 415 555 0199"},
    )
    assert r.status_code == 200 and (r.json()["first_name"], r.json()["last_name"], r.json()["phone"]) == (
        "Grace",
        "Hopper",
        "+1 415 555 0199",
    )
    assert (
        await scalar(
            "SELECT display_name FROM candidate_profiles WHERE user_id = :u", u=uuid.UUID(cand["user"]["id"])
        )
        == "Grace Hopper"
    )
    cleared = await client.patch(f"{API}/auth/me", headers=cand["h"], json={"phone": None})
    assert cleared.json()["phone"] is None and cleared.json()["first_name"] == "Grace"
    assert_error(
        await client.patch(f"{API}/auth/me", headers=cand["h"], json={"phone": "abc"}),
        422,
        "VALIDATION_ERROR",
    )


async def test_update_me_cannot_escalate_privileges(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.patch(
        f"{API}/auth/me",
        headers=cand["h"],
        json={
            "role": "ADMIN",
            "status": "ACTIVE",
            "company_id": str(uuid.uuid4()),
            "email": "evil@example.com",
            "password_hash": "x",
        },
    )
    assert r.status_code == 200
    me = r.json()
    assert me["role"] == "CANDIDATE" and me["email"] == cand["email"] and me["company_id"] is None


# --- bearer-token handling ------------------------------------------------------------------------------------------------------------------------------


async def test_missing_credentials(client: AsyncClient) -> None:
    r = await client.get(f"{API}/auth/me")
    assert_error(r, 401, "UNAUTHORIZED")
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic dXNlcjpwYXNz", "Token abc", "abc", ""])
async def test_non_bearer_authorization_headers_count_as_unauthenticated(
    client: AsyncClient, header: str
) -> None:
    assert_error(await client.get(f"{API}/auth/me", headers={"Authorization": header}), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "x" * 400, "eyJhbGciOiJub25lIn0.e30."])
async def test_garbage_bearer_tokens(client: AsyncClient, token: str) -> None:
    assert_error(await client.get(f"{API}/auth/me", headers=auth(token)), 401, "INVALID_TOKEN")


async def test_expired_token(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    expired, _ = create_access_token(cand["user"]["id"], "CANDIDATE", expires_minutes=-5)
    assert_error(await client.get(f"{API}/auth/me", headers=auth(expired)), 401, "TOKEN_EXPIRED")


async def test_tampered_token(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    head, payload, sig = cand["token"].split(".")
    assert_error(
        await client.get(f"{API}/auth/me", headers=auth(f"{head}.{payload}.{sig[:-2]}ab")),
        401,
        "INVALID_TOKEN",
    )


async def test_token_for_a_deleted_user_or_with_a_bad_subject(client: AsyncClient) -> None:
    ghost, _ = create_access_token(uuid.uuid4(), "ADMIN")
    assert_error(await client.get(f"{API}/auth/me", headers=auth(ghost)), 401, "INVALID_TOKEN")
    odd, _ = create_access_token("not-a-uuid", "ADMIN")
    assert_error(await client.get(f"{API}/auth/me", headers=auth(odd)), 401, "INVALID_TOKEN")


async def test_the_role_claim_in_the_token_is_not_trusted(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    forged, _ = create_access_token(
        cand["user"]["id"], "ADMIN"
    )  # validly signed, but claims a role the user does not have
    assert (await client.get(f"{API}/auth/me", headers=auth(forged))).json()["role"] == "CANDIDATE"
    assert_error(await client.get(f"{API}/users", headers=auth(forged)), 403, "FORBIDDEN")


async def test_a_presented_but_invalid_token_is_an_error_even_on_public_routes(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/skills")).status_code == 200
    assert (await client.get(f"{API}/search/jobs")).status_code == 200
    assert_error(await client.get(f"{API}/search/jobs", headers=auth("garbage")), 401, "INVALID_TOKEN")


# --- rate limiting / lockout ------------------------------------------------------------------------------------------------------------------------------------


async def test_failed_logins_lock_the_account_per_email_and_say_when_to_retry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cand = await register_candidate(client)
    other = await register_candidate(client)
    monkeypatch.setattr(get_settings(), "login_rate_limit_attempts", 3)
    monkeypatch.setattr(get_settings(), "login_rate_limit_window_seconds", 120)
    for i in range(3):  # different source addresses, so only the per-account counter can trip
        async with client_from(f"10.1.0.{i}") as c:
            assert_error(await login(c, cand["email"], "WrongPassword99"), 401, "INVALID_CREDENTIALS")
    async with client_from("10.1.0.9") as c:
        locked = await login(c, cand["email"], PASSWORD)  # even the right password is refused while locked
        err = assert_error(locked, 429, "RATE_LIMITED")
        assert 1 <= int(locked.headers["retry-after"]) <= 120 and err["details"] == {
            "retry_after_seconds": int(locked.headers["retry-after"])
        }
        assert (await login(c, other["email"], PASSWORD)).status_code == 200, "other accounts are unaffected"
        assert_error(
            await login(c, cand["email"].upper(), PASSWORD), 429, "RATE_LIMITED"
        )  # case variants share the counter


async def test_a_successful_login_resets_the_failure_counter(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cand = await register_candidate(client)
    monkeypatch.setattr(get_settings(), "login_rate_limit_attempts", 3)
    for round_ in range(3):
        async with client_from(f"10.2.{round_}.1") as c:
            for _ in range(2):
                assert_error(await login(c, cand["email"], "WrongPassword99"), 401, "INVALID_CREDENTIALS")
            assert (await login(c, cand["email"], PASSWORD)).status_code == 200


async def test_login_is_also_limited_per_client_address(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cand = await register_candidate(client)
    monkeypatch.setattr(get_settings(), "login_rate_limit_attempts", 3)
    async with client_from("10.3.0.1") as noisy, client_from("10.3.0.2") as quiet:
        for _ in range(3):
            assert (await login(noisy, cand["email"])).status_code == 200
        r = await login(noisy, cand["email"])
        err = assert_error(r, 429, "RATE_LIMITED")
        assert int(r.headers["retry-after"]) >= 1 and "retry_after_seconds" in err["details"]
        assert (await login(quiet, cand["email"])).status_code == 200, "limits are per client"
        # the OAuth2 form endpoint shares the same bucket
        assert (
            await noisy.post(f"{API}/auth/token", data={"username": cand["email"], "password": PASSWORD})
        ).status_code == 429


async def test_registration_is_limited_per_client_address(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "register_rate_limit_attempts", 2)
    async with client_from("10.4.0.1") as c, client_from("10.4.0.2") as d:
        assert (await c.post(REG, json=candidate_body())).status_code == 201
        assert (await c.post(REG_EMP, json=employer_body())).status_code == 201
        r = await c.post(REG, json=candidate_body())
        assert_error(r, 429, "RATE_LIMITED")
        assert "retry-after" in r.headers
        assert (await d.post(REG, json=candidate_body())).status_code == 201


async def test_staff_accounts_created_by_admins_can_log_in(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    assert hm["user"]["role"] == "HIRING_MANAGER" and hm["user"]["company_id"] == rec["company_id"]
    assert datetime.fromisoformat(hm["user"]["created_at"]) <= datetime.now(UTC) + timedelta(seconds=5)
