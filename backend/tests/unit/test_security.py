"""Password hashing, JWT access tokens, refresh tokens and the role -> permission matrix."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from argon2 import PasswordHasher

from app.core import security
from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import (
    ROLE_PERMISSIONS,
    STAFF_ROLES,
    Permission,
    Role,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    has_permission,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)

SECRET = get_settings().secret_key.get_secret_value()
ALG = get_settings().jwt_algorithm


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "role": "CANDIDATE",
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "jti": uuid.uuid4().hex,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def _forge(claims: dict[str, object], key: str = SECRET, alg: str = ALG) -> str:
    return jwt.encode(claims, key, algorithm=alg)


def _b64(data: dict[str, object] | bytes) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- passwords -----------------------------------------------------------------------------------------------


def test_hash_is_argon2id_salted_and_verifiable() -> None:
    h1, h2 = hash_password("CorrectHorse42"), hash_password("CorrectHorse42")
    assert h1.startswith("$argon2id$") and h1 != h2  # unique salt per hash
    assert verify_password("CorrectHorse42", h1) and verify_password("CorrectHorse42", h2)
    assert "CorrectHorse42" not in h1


@pytest.mark.parametrize(
    "wrong", ["correcthorse42", "CorrectHorse4", "CorrectHorse42 ", "", " ", "CorrectHorse42\x00"]
)
def test_wrong_password_is_rejected(wrong: str) -> None:
    assert verify_password(wrong, hash_password("CorrectHorse42")) is False


def test_unicode_and_long_passwords() -> None:
    for pw in ("pässwörd-密码-🔑42", "a1" * 60):
        assert verify_password(pw, hash_password(pw))


@pytest.mark.parametrize(
    "garbage", ["", "not-a-hash", "$argon2id$broken", "$2b$12$abcdefghijklmnopqrstuuxyz"]
)
def test_malformed_stored_hash_fails_closed(garbage: str) -> None:
    assert verify_password("CorrectHorse42", garbage) is False


def test_unknown_user_path_burns_a_real_hash_and_never_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = security._hasher

    class Spy:
        def verify(self, h: str, p: str) -> bool:
            calls.append(h)
            return real.verify(h, p)

    monkeypatch.setattr(security, "_hasher", Spy())
    assert verify_password("anything", None) is False
    assert calls == [security._DUMMY_HASH], "timing equaliser must verify against a genuine Argon2 hash"
    assert security._DUMMY_HASH.startswith("$argon2id$")
    # even the dummy's own password must not authenticate a non-existent user
    assert verify_password("timing-equaliser-not-a-real-password", None) is False


def test_needs_rehash_detects_weaker_parameters() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("CorrectHorse42")
    assert needs_rehash(weak) is True
    assert needs_rehash(hash_password("CorrectHorse42")) is False
    assert verify_password("CorrectHorse42", weak) is True  # old hashes keep working until upgraded


# --- access tokens -----------------------------------------------------------------------------------------------


def test_access_token_roundtrip_and_claims() -> None:
    uid = uuid.uuid4()
    token, expires_in = create_access_token(uid, "RECRUITER")
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid) and payload["role"] == "RECRUITER" and payload["type"] == "access"
    assert expires_in == get_settings().access_token_expire_minutes * 60
    assert payload["exp"] - payload["iat"] == expires_in
    assert len(payload["jti"]) == 32


def test_each_token_has_a_unique_jti() -> None:
    uid = uuid.uuid4()
    assert (
        len({decode_access_token(create_access_token(uid, "CANDIDATE")[0])["jti"] for _ in range(20)}) == 20
    )


def test_custom_lifetime() -> None:
    token, ttl = create_access_token(uuid.uuid4(), "ADMIN", expires_minutes=1)
    assert ttl == 60 and decode_access_token(token)["exp"] - time.time() <= 61


def test_expired_token_has_its_own_code() -> None:
    token = _forge(
        _claims(exp=datetime.now(UTC) - timedelta(seconds=5), iat=datetime.now(UTC) - timedelta(minutes=10))
    )
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(token)
    assert exc.value.code == "TOKEN_EXPIRED" and exc.value.status_code == 401


def _assert_invalid(token: str) -> None:
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(token)
    assert exc.value.code == "INVALID_TOKEN" and exc.value.status_code == 401


def test_tampered_payload_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), "CANDIDATE")
    head, payload, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["role"] == "CANDIDATE"
    elevated = _b64({**claims, "role": "ADMIN"})
    _assert_invalid(f"{head}.{elevated}.{sig}")


def test_tampered_signature_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), "CANDIDATE")
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    _assert_invalid(f"{head}.{payload}.{flipped}")
    _assert_invalid(f"{head}.{payload}.")
    _assert_invalid(f"{head}.{payload}")


def test_alg_none_is_rejected() -> None:
    header = _b64({"alg": "none", "typ": "JWT"})
    now = int(time.time())
    body = _b64(
        {
            "sub": str(uuid.uuid4()),
            "role": "ADMIN",
            "type": "access",
            "iat": now,
            "exp": now + 600,
            "jti": "x",
        }
    )
    _assert_invalid(f"{header}.{body}.")
    _assert_invalid(f"{header}.{body}")
    unsigned = jwt.encode(_claims(role="ADMIN"), key=None, algorithm="none")
    _assert_invalid(unsigned)


@pytest.mark.filterwarnings("ignore:The HMAC key is")
def test_algorithm_allow_list_blocks_other_hmac_variants() -> None:
    other = "HS512" if ALG != "HS512" else "HS384"
    _assert_invalid(_forge(_claims(), alg=other))


def test_token_signed_with_another_secret_is_rejected() -> None:
    _assert_invalid(_forge(_claims(), key="x" * 40))


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "jti"])
def test_required_claims_must_be_present(missing: str) -> None:
    _assert_invalid(_forge(_claims(**{missing: None})))


def test_wrong_or_missing_token_type_is_rejected() -> None:
    _assert_invalid(_forge(_claims(type="refresh")))
    _assert_invalid(_forge(_claims(type=None)))


def test_not_yet_valid_token_is_rejected() -> None:
    _assert_invalid(_forge(_claims(nbf=datetime.now(UTC) + timedelta(minutes=10))))


@pytest.mark.parametrize(
    "garbage", ["", "x", "a.b", "a.b.c", "Bearer abc", "....", " ", "null", "eyJhbGciOiJIUzI1NiJ9.e30.abc"]
)
def test_garbage_is_invalid_not_a_crash(garbage: str) -> None:
    _assert_invalid(garbage)


# --- refresh tokens -------------------------------------------------------------------------------------------------


def test_refresh_tokens_are_long_random_and_url_safe() -> None:
    tokens = {generate_refresh_token() for _ in range(200)}
    assert len(tokens) == 200
    for t in tokens:
        assert len(t) >= 64 and all(c.isalnum() or c in "-_" for c in t)


def test_refresh_token_hash_is_sha256_hex_and_deterministic() -> None:
    t = generate_refresh_token()
    assert hash_refresh_token(t) == hash_refresh_token(t)
    assert len(hash_refresh_token(t)) == 64 and set(hash_refresh_token(t)) <= set("0123456789abcdef")
    assert t not in hash_refresh_token(t)
    assert hash_refresh_token(t) != hash_refresh_token(t + "x")
    assert hash_refresh_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# --- permission matrix --------------------------------------------------------------------------------------------------

P = Permission
EXPECTED: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.RECRUITER: {
        P.MANAGE_OWN_COMPANY,
        P.CREATE_SKILL,
        P.MANAGE_JOBS,
        P.VIEW_COMPANY_JOBS,
        P.SEARCH_CANDIDATES,
        P.VIEW_CANDIDATES,
        P.MANAGE_APPLICATIONS,
        P.REVIEW_APPLICATIONS,
        P.IMPORT_RESUMES,
        P.SCHEDULE_INTERVIEWS,
        P.VIEW_INTERVIEWS,
        P.PROVIDE_FEEDBACK,
        P.VIEW_MATCHES,
        P.RUN_MATCHING,
        P.VIEW_REPORTS,
    },
    Role.HIRING_MANAGER: {
        P.VIEW_COMPANY_JOBS,
        P.VIEW_CANDIDATES,
        P.REVIEW_APPLICATIONS,
        P.VIEW_INTERVIEWS,
        P.PROVIDE_FEEDBACK,
        P.VIEW_MATCHES,
        P.VIEW_REPORTS,
    },
    Role.CANDIDATE: {
        P.CREATE_SKILL,
        P.MANAGE_OWN_PROFILE,
        P.APPLY_TO_JOBS,
        P.UPLOAD_RESUME,
        P.VIEW_INTERVIEWS,
        P.VIEW_RECOMMENDATIONS,
    },
}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("permission", list(Permission))
def test_permission_matrix_cell(role: Role, permission: Permission) -> None:
    assert has_permission(role, permission) is (permission in EXPECTED[role])


def test_matrix_covers_every_role_and_has_no_stray_entries() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert {r: set(p) for r, p in ROLE_PERMISSIONS.items()} == EXPECTED


def test_headline_permission_rules() -> None:
    assert not has_permission(Role.CANDIDATE, P.MANAGE_JOBS)
    assert not has_permission(Role.HIRING_MANAGER, P.MANAGE_APPLICATIONS)
    assert not has_permission(Role.HIRING_MANAGER, P.MANAGE_JOBS)
    assert not has_permission(Role.RECRUITER, P.MANAGE_USERS)
    assert not has_permission(Role.RECRUITER, P.MONITOR_SYSTEM)
    assert not has_permission(Role.CANDIDATE, P.SEARCH_CANDIDATES)
    assert all(has_permission(Role.ADMIN, p) for p in Permission)
    assert has_permission("RECRUITER", P.MANAGE_JOBS)  # string role names (as stored/serialised) work too


def test_least_privilege_ordering() -> None:
    # a hiring manager can do nothing a recruiter cannot, except nothing: HM is a strict subset of RECRUITER
    assert ROLE_PERMISSIONS[Role.HIRING_MANAGER] < ROLE_PERMISSIONS[Role.RECRUITER]
    assert ROLE_PERMISSIONS[Role.RECRUITER] < ROLE_PERMISSIONS[Role.ADMIN]
    staff_only = {
        P.SEARCH_CANDIDATES,
        P.VIEW_CANDIDATES,
        P.MANAGE_APPLICATIONS,
        P.REVIEW_APPLICATIONS,
        P.MANAGE_JOBS,
    }
    assert not staff_only & ROLE_PERMISSIONS[Role.CANDIDATE]


def test_staff_roles() -> None:
    assert {Role.RECRUITER, Role.HIRING_MANAGER} == STAFF_ROLES
