from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from mod1_auth.database import create_session_factory, initialize_database
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRepository
from mod1_auth.services import UserService


def authorization(client, user):
    token = client.post(
        "/auth/token", data={"username": user.email, "password": "  password12345  "}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_unsaved_profile_returns_defaults_without_writing(client, user, engine):
    response = client.get("/auth/profile", headers=authorization(client, user))
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user.id),
        "summary": "",
        "seniority": "not_informed",
        "weekly_availability_hours": 0,
        "skills": [],
    }
    assert response.headers["cache-control"] == "no-store"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM profiles")).scalar() == 0


def test_partial_profile_persists_after_restart_and_cannot_access_other_account(
    client, user, engine, settings
):
    headers = authorization(client, user)
    profile = {
        "summary": "Olá 👩🏽‍💻",
        "seniority": "senior",
        "weekly_availability_hours": 168,
        "skills": [{"name": "  Python  ", "level": 5}],
    }
    response = client.patch("/auth/profile", headers=headers, json=profile)
    assert response.status_code == 200
    expected = profile | {"user_id": str(user.id), "skills": [{"name": "Python", "level": 5}]}
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/auth/profile", headers=headers).json() == expected
        patched = restarted.patch("/auth/profile", headers=headers, json={"summary": ""})
        assert patched.json() == expected | {"summary": ""}
    with create_session_factory(engine)() as session:
        other = UserService(UserRepository(session)).create_user(
            email="other@example.com", display_name="Other", password="  password12345  "
        )
    other_headers = authorization(client, other)
    assert client.get("/auth/profile", headers=other_headers).json()["skills"] == []
    assert client.get(f"/auth/profile/{user.id}", headers=other_headers).status_code == 404
    clear = client.patch(
        "/auth/profile",
        headers=headers,
        json={"skills": [], "seniority": "not_informed", "weekly_availability_hours": 0},
    )
    assert clear.json()["skills"] == []
    assert clear.json()["seniority"] == "not_informed"


@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.parametrize("kind", ["missing", "malformed", "unknown", "inactive", "expired"])
def test_profile_requires_existing_active_authenticated_identity(
    client, user, engine, method, kind
):
    headers = {}
    if kind == "malformed":
        headers = {"Authorization": "Bearer invalid"}
    elif kind in ("unknown", "expired"):
        from datetime import UTC, datetime, timedelta

        import jwt

        tokens = client.app.state.tokens
        claims = jwt.decode(tokens.issue(user.id).access_token, options={"verify_signature": False})
        if kind == "unknown":
            claims["sub"] = str(uuid4())
        else:
            claims["iat"] = int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())
            claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        token = jwt.encode(
            claims,
            client.app.state.keys.private_key,
            algorithm="RS256",
            headers={"kid": client.app.state.keys.kid},
        )
        headers = {"Authorization": f"Bearer {token}"}
    elif kind == "inactive":
        headers = authorization(client, user)
        with create_session_factory(engine)() as session:
            UserRepository(session).set_active(user.id, False)
    kwargs = {"json": {"summary": "private"}} if method == "patch" else {}
    response = getattr(client, method)("/auth/profile", headers=headers, **kwargs)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"user_id": str(uuid4())},
        {"summary": None},
        {"summary": 123},
        {"summary": "x" * 2001},
        {"seniority": "expert"},
        {"seniority": None},
        {"weekly_availability_hours": -1},
        {"weekly_availability_hours": 169},
        {"weekly_availability_hours": True},
        {"weekly_availability_hours": 1.0},
        {"weekly_availability_hours": "1"},
        {"skills": None},
        {"skills": [{}]},
        {"skills": [{"name": " ", "level": 1}]},
        {"skills": [{"name": "x" * 81, "level": 1}]},
        {"skills": [{"name": "secret", "level": True}]},
        {"skills": [{"name": "secret", "level": 1.0}]},
        {"skills": [{"name": "secret", "level": 0}]},
        {"skills": [{"name": "secret", "level": 6}]},
        {"skills": [{"name": "secret", "level": None}]},
        {"skills": [{"name": "secret", "level": 1, "extra": "private"}]},
        {"skills": [{"name": "Straße", "level": 1}, {"name": "STRASSE", "level": 2}]},
        {"skills": [{"name": "é", "level": 1}, {"name": "e\u0301", "level": 2}]},
        {"skills": [{"name": str(index), "level": 1} for index in range(31)]},
    ],
)
def test_profile_rejects_invalid_partial_input_without_echo_or_changes(client, user, payload):
    headers = authorization(client, user)
    response = client.patch("/auth/profile", headers=headers, json=payload)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text and "secret" not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])
    assert client.get("/auth/profile", headers=headers).json()["summary"] == ""


def test_profile_accepts_exact_boundaries(client, user):
    profile = {
        "summary": "👩" * 2000,
        "seniority": "lead",
        "weekly_availability_hours": 0,
        "skills": [{"name": str(index).ljust(80, "é"), "level": 1} for index in range(30)],
    }
    response = client.patch("/auth/profile", headers=authorization(client, user), json=profile)
    assert response.status_code == 200
    assert response.json() == profile | {"user_id": str(user.id)}


@pytest.mark.parametrize("method", ["get", "patch"])
def test_profile_database_failure_is_generic_and_not_cached(client, user, engine, method):
    headers = authorization(client, user)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE profiles"))
    kwargs = {"json": {"summary": "private"}} if method == "patch" else {}
    response = getattr(client, method)("/auth/profile", headers=headers, **kwargs)
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_schema_upgrade_is_explicit_idempotent_and_preserves_accounts(engine, user, settings):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE profiles"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
    assert "profiles" not in inspect(engine).get_table_names()
    initialize_database(engine)
    initialize_database(engine)
    assert inspect(engine).get_foreign_keys("profiles")[0]["referred_table"] == "users"
    with create_session_factory(engine)() as session:
        assert UserRepository(session).get_by_id(user.id) == user


def test_parallel_partial_profile_updates_preserve_both_changes(client, user):
    headers = authorization(client, user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda patch: client.patch("/auth/profile", headers=headers, json=patch),
                [{"summary": "saved"}, {"skills": [{"name": "SQL", "level": 3}]}],
            )
        )
    assert [response.status_code for response in responses] == [200, 200]
    saved = client.get("/auth/profile", headers=headers).json()
    assert saved["summary"] == "saved"
    assert saved["skills"] == [{"name": "SQL", "level": 3}]


def test_profile_openapi_and_browser_preflight(client, settings, engine):
    paths = client.get("/openapi.json").json()["paths"]
    for method in ("get", "patch"):
        operation = paths["/auth/profile"][method]
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
        assert {"200", "401", "422", "503"} <= operation["responses"].keys()
    settings.cors_origins = ["http://localhost:8080"]
    with TestClient(create_app(settings)) as browser:
        response = browser.options(
            "/auth/profile",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200
