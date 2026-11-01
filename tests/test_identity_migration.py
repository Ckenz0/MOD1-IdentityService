from fastapi.testclient import TestClient
from test_sessions import login

from mod1_auth.database import create_session_factory, initialize_database
from mod1_auth.identity_repository import SecurityDocument, SecurityMutex
from mod1_auth.main import create_app
from mod1_auth.repositories import UserRepository


def test_old_database_is_migrated_explicitly_without_losing_users(settings, engine, user):
    # Simulate the preceding release, whose users/profiles tables remain unchanged.
    SecurityDocument.__table__.drop(engine)
    SecurityMutex.__table__.drop(engine)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 503
        assert login(client, user).status_code == 503
    initialize_database(engine)
    initialize_database(engine)
    with create_session_factory(engine)() as session:
        restored = UserRepository(session).get_by_id(user.id)
        assert restored.password_hash == user.password_hash
        assert restored.created_at == user.created_at
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 200
        assert login(client, user).status_code == 200


def test_persisted_refresh_is_hashed(client, engine, user):
    response = login(client, user).json()
    with create_session_factory(engine)() as session:
        rows = session.query(SecurityDocument).filter(SecurityDocument.kind != "mail").all()
        persisted = str([(row.key, row.data) for row in rows])
        assert response["refresh_token"] not in persisted
        assert response["access_token"] not in persisted
