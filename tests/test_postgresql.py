"""Integracao opt-in somente com PostgreSQL local descartavel, nunca um banco remoto."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import DropSchema

from mod1_auth.database import create_engine_for_url, create_session_factory, initialize_database
from mod1_auth.domain import DuplicateEmailError
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRepository
from mod1_auth.services import UserService


@pytest.fixture
def pg_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL absent: PostgreSQL integration not verified")
    parsed = make_url(url)
    if (
        parsed.host not in ("localhost", "127.0.0.1", "::1", "db")
        or parsed.get_backend_name() != "postgresql"
        or "host" in parsed.query
        or "hostaddr" in parsed.query
    ):
        pytest.fail("Use only disposable local PostgreSQL for these tests")
    schema = "test_auth_" + uuid4().hex
    engine = create_engine_for_url(url, schema=schema)
    initialize_database(engine)
    try:
        yield url, schema, engine
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_postgresql_normalization_duplicate_and_rollback(pg_database):
    _, _, engine = pg_database
    with create_session_factory(engine)() as session:
        service = UserService(UserRepository(session))
        user = service.create_user(
            email=" Caue@Example.com ", display_name="Caue", password="password12345"
        )
        with pytest.raises(DuplicateEmailError):
            service.create_user(
                email="caue@example.com", display_name="Other", password="password12345"
            )
        second = service.create_user(
            email="other@example.com", display_name="Other", password="password12345"
        )
        assert second.id != user.id
    with create_session_factory(engine)() as session:
        reloaded = UserRepository(session).get_by_id(user.id)
        assert reloaded.email == "caue@example.com"
        assert reloaded.created_at == user.created_at


def test_postgresql_login_and_restart(pg_database, settings):
    url, schema, engine = pg_database
    settings.database_url = type(settings.database_url)(url)
    settings.database_schema = schema
    with create_session_factory(engine)() as session:
        UserService(UserRepository(session)).create_user(
            email="a@example.com", display_name="A", password="password12345"
        )
    with TestClient(create_app(settings)) as first:
        token = first.post(
            "/auth/token", data={"username": "a@example.com", "password": "password12345"}
        ).json()["access_token"]
        first_me = first.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    with TestClient(create_app(settings)) as second:
        me = second.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json() == first_me


def test_postgresql_password_change_persists_and_rejects_stale_hash(pg_database, settings):
    url, schema, engine = pg_database
    settings.database_url = type(settings.database_url)(url)
    settings.database_schema = schema
    with create_session_factory(engine)() as session:
        user = UserService(UserRepository(session)).create_user(
            email="password@example.com", display_name="Password", password="password12345"
        )
    with TestClient(create_app(settings)) as client:
        token = client.post(
            "/auth/token", data={"username": user.email, "password": "password12345"}
        ).json()["access_token"]
        changed = client.post(
            "/auth/password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": "password12345", "new_password": "  nova senha literal  "},
        )
        assert changed.status_code == 204
    with create_session_factory(engine)() as session:
        repository = UserRepository(session)
        assert not repository.change_password(user.id, user.password_hash, "stale")
    with TestClient(create_app(settings)) as restarted:
        for password, status in [("password12345", 401), ("  nova senha literal  ", 200)]:
            assert (
                restarted.post(
                    "/auth/token", data={"username": user.email, "password": password}
                ).status_code
                == status
            )


def test_postgresql_missing_schema_is_not_liveness_failure(pg_database, settings):
    url, _, _ = pg_database
    settings.database_url = type(settings.database_url)(url)
    settings.database_schema = "uninitialized_" + uuid4().hex
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_postgresql_permission_failure_is_not_liveness_failure(pg_database, settings):
    url, schema, engine = pg_database
    role = "test_denied_" + uuid4().hex
    password = uuid4().hex + uuid4().hex
    quoted_role = engine.dialect.identifier_preparer.quote(role)
    # Fixed-prefix UUID role and UUID-only synthetic password; never external identifiers.
    with engine.begin() as connection:
        connection.execute(text(f"CREATE ROLE {quoted_role} LOGIN PASSWORD '{password}'"))
    denied_url = make_url(url).set(username=role, password=password)
    settings.database_url = type(settings.database_url)(
        denied_url.render_as_string(hide_password=False)
    )
    settings.database_schema = schema
    try:
        # This role has no USAGE on the real, initialized schema or SELECT on users.
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
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP ROLE {quoted_role}"))


def test_runtime_role_cannot_read_another_schema(pg_database):
    url, schema, engine = pg_database
    role = "test_role_" + uuid4().hex
    other = "test_other_" + uuid4().hex
    # Identifiers are internally generated from fixed prefixes and UUID hex.
    preparer = engine.dialect.identifier_preparer
    quoted_role, quoted_other, quoted_schema = map(preparer.quote, (role, other, schema))
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
            connection.execute(text(f"CREATE SCHEMA {quoted_other}"))
            connection.execute(text(f"CREATE TABLE {quoted_other}.private_data (id integer)"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {quoted_schema} TO {quoted_role}"))
            connection.execute(
                text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {quoted_schema} TO {quoted_role}")
            )
        with engine.connect() as connection:
            connection.execute(text(f"SET LOCAL ROLE {quoted_role}"))
            connection.execute(text(f"SELECT id FROM {quoted_schema}.users"))
            with pytest.raises(SQLAlchemyError):
                connection.execute(text(f"SELECT id FROM {quoted_other}.private_data"))
            connection.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_other} CASCADE"))
            connection.execute(text(f"DROP OWNED BY {quoted_role}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
