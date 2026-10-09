import pytest

pytestmark = pytest.mark.e2e


async def test_register_login_me(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "Ada@Example.com",
            "password": "CorrectHorse42",
            "first_name": "Ada",
            "last_name": "L",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["role"] == "CANDIDATE"
    assert body["user"]["candidate_id"]
    assert "password" not in r.text
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    dup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada@example.com",
            "password": "CorrectHorse42",
            "first_name": "Ada",
            "last_name": "L",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
