import socket
from importlib.metadata import version
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mod1_auth.database import create_session_factory
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRecord, UserRepository
from mod1_auth.security import TokenService, load_key_material


def login(client, **extra):
    return client.post(
        "/auth/token",
        data=dict(username=" CAUE@EXAMPLE.COM ", password="  password12345  ") | extra,
    )


def test_login_identity_and_public_jwks(client, user):
    response = login(client, aud="attacker", roles="admin")
    assert response.status_code == 200
    assert response.json()["expires_in"] == 1800
    assert response.headers["cache-control"] == "no-store"
    token = response.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert set(me.json()) == {
        "id",
        "email",
        "display_name",
        "is_active",
        "created_at",
        "is_admin",
        "email_verified",
    }
    assert me.json()["id"] == str(user.id)
    assert me.json()["email"] == "caue@example.com"
    assert client.get("/.well-known/jwks.json").status_code == 200
    assert client.post("/auth/token", data={"username": "a"}).status_code == 422


@pytest.mark.parametrize("kind", ["password", "missing", "inactive", "stripped"])
def test_login_uniform_failure(client, user, engine, kind):
    extra = {}
    if kind == "missing":
        extra["username"] = "absent@example.com"
    elif kind == "inactive":
        with create_session_factory(engine)() as session:
            UserRepository(session).set_active(user.id, False)
    else:
        extra["password"] = "wrong" if kind == "password" else "password12345"
    response = login(client, **extra)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("kind", ["missing", "malformed", "invalid", "unknown", "inactive"])
def test_me_rejects_missing_invalid_unknown_or_inactive_identity(
    client, user, engine, settings, kind
):
    headers = {}
    if kind == "malformed":
        headers = {"Authorization": "Basic invalid"}
    elif kind == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    elif kind in ("unknown", "inactive"):
        tokens = TokenService(load_key_material(settings.jwt_private_key_path), settings)
        token = tokens.issue(uuid4() if kind == "unknown" else user.id).access_token
        headers = {"Authorization": f"Bearer {token}"}
        if kind == "inactive":
            with create_session_factory(engine)() as session:
                UserRepository(session).set_active(user.id, False)
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_health_and_database_failure(client, engine):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    UserRecord.__table__.drop(engine)
    assert client.get("/health/live").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}


def test_uninitialized_database_is_not_ready(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_unreachable_database_is_not_liveness_failure(settings, tmp_path, backend):
    if backend == "postgresql":
        pytest.importorskip(
            "psycopg", reason="PostgreSQL driver unavailable on this host", exc_type=ImportError
        )
    # A bound socket without listen() keeps the port reserved and refuses TCP connections.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        url = f"postgresql+psycopg://synthetic:synthetic@127.0.0.1:{port}/auth"
        if backend == "sqlite":
            url = f"sqlite:///{tmp_path / 'missing-directory' / 'unreachable.db'}"
        settings.database_url = type(settings.database_url)(url)
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
            ready = client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "unavailable"}
            login = client.post(
                "/auth/token", data={"username": "a@example.com", "password": "synthetic-password"}
            )
            assert login.status_code == 503
            assert login.json() == {"detail": "Service unavailable"}


def test_startup_requires_valid_key(settings, tmp_path):
    settings.jwt_private_key_path = tmp_path / "missing.pem"
    with pytest.raises((FileNotFoundError, RuntimeError)):
        with TestClient(create_app(settings)):
            pass
    settings.jwt_private_key_path.write_text("invalid PEM")
    with pytest.raises((ValueError, RuntimeError)):
        with TestClient(create_app(settings)):
            pass


def test_openapi_and_cors(client, settings, engine):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == version("mod1-auth")
    assert (
        schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"][
            "tokenUrl"
        ]
        == "/auth/token"
    )
    assert schema["paths"]["/auth/me"]["get"]["security"]
    assert not schema["paths"]["/.well-known/jwks.json"]["get"].get("security")
    assert client.get("/docs").status_code == 200
    assert (
        "access-control-allow-origin"
        not in client.get(
            "/health/live", headers={"Origin": "https://frontend.example.com"}
        ).headers
    )
    settings.cors_origins = ["https://frontend.example.com"]
    with TestClient(create_app(settings)) as allowed:
        assert (
            allowed.get("/health/live", headers={"Origin": "https://frontend.example.com"}).headers[
                "access-control-allow-origin"
            ]
            == "https://frontend.example.com"
        )
        assert (
            "access-control-allow-origin"
            not in allowed.get(
                "/health/live", headers={"Origin": "https://other.example.com"}
            ).headers
        )
