from uuid import UUID, uuid4

import pytest

from mod1_auth.cli import main
from mod1_auth.database import create_engine_for_url, create_session_factory
from mod1_auth.domain import InvalidCredentialsError
from mod1_auth.repositories import UserRepository
from mod1_auth.security import TokenService, load_key_material, verify_password
from mod1_auth.services import AuthService


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(tmp_path / "keys" / "auth.pem"))
    monkeypatch.setenv("JWT_ISSUER", "test-issuer")
    return tmp_path


def create(
    monkeypatch,
    password="  password12345  ",
    confirmation=None,
    email="caue@example.com",
    name="Caue",
):
    values = iter([password, password if confirmation is None else confirmation])
    monkeypatch.setattr("mod1_auth.cli.getpass.getpass", lambda prompt: next(values))
    return main(["create-user", "--email", email, "--name", name])


def test_init_preserves_existing_key_and_users(cli_env, monkeypatch):
    assert main(["init"]) == 0
    path = cli_env / "keys" / "auth.pem"
    original = path.read_bytes()
    assert create(monkeypatch) == 0
    assert main(["init"]) == 0
    assert path.read_bytes() == original
    engine = create_engine_for_url(f"sqlite:///{cli_env / 'cli.db'}")
    with create_session_factory(engine)() as session:
        assert UserRepository(session).get_by_email("caue@example.com") is not None
    engine.dispose()


def test_create_user_uses_hidden_confirmed_password(cli_env, monkeypatch, capsys):
    assert main(["init"]) == 0
    assert create(monkeypatch) == 0
    result = capsys.readouterr()
    assert "caue@example.com" in result.out
    assert "password12345" not in result.out + result.err
    assert "$argon2" not in result.out + result.err
    engine = create_engine_for_url(f"sqlite:///{cli_env / 'cli.db'}")
    with create_session_factory(engine)() as session:
        user = UserRepository(session).get_by_email("caue@example.com")
        assert UUID(str(user.id))
        assert verify_password("  password12345  ", user.password_hash)
    engine.dispose()


@pytest.mark.parametrize(
    "values",
    [
        {"confirmation": "different"},
        {"password": "short"},
        {"password": "x" * 129},
        {"email": "invalid"},
        {"name": " "},
    ],
)
def test_create_rejects_invalid_input(cli_env, monkeypatch, values):
    assert main(["init"]) == 0
    assert create(monkeypatch, **values) != 0
    engine = create_engine_for_url(f"sqlite:///{cli_env / 'cli.db'}")
    with create_session_factory(engine)() as session:
        assert UserRepository(session).get_by_email("caue@example.com") is None
    engine.dispose()


def test_cli_uses_configured_password_policy(cli_env, monkeypatch):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "24")
    assert main(["init"]) == 0
    assert create(monkeypatch, password="x" * 23) == 1
    assert create(monkeypatch, password="x" * 24) == 0


def test_duplicate_email_returns_error(cli_env, monkeypatch):
    assert main(["init"]) == 0
    assert create(monkeypatch) == 0
    assert create(monkeypatch, email=" CAUE@example.com ") != 0


def test_set_active_controls_existing_identity(cli_env, monkeypatch):
    assert main(["init"]) == 0
    assert create(monkeypatch) == 0
    engine = create_engine_for_url(f"sqlite:///{cli_env / 'cli.db'}")
    with create_session_factory(engine)() as session:
        user = UserRepository(session).get_by_email("caue@example.com")
    assert main(["set-active", "--user-id", str(user.id), "--inactive"]) == 0
    from mod1_auth.config import Settings

    settings = Settings()
    with create_session_factory(engine)() as session:
        auth = AuthService(
            UserRepository(session),
            TokenService(load_key_material(settings.jwt_private_key_path), settings),
        )
        with pytest.raises(InvalidCredentialsError):
            auth.authenticate(user.email, "  password12345  ")
        assert main(["set-active", "--user-id", str(user.id), "--active"]) == 0
        session.expire_all()
        assert auth.authenticate(user.email, "  password12345  ").access_token
    assert main(["set-active", "--user-id", str(uuid4()), "--inactive"]) != 0
    with pytest.raises(SystemExit):
        main(["set-active", "--user-id", "invalid", "--inactive"])
    engine.dispose()


@pytest.mark.parametrize("flag", ["--password", "--role"])
def test_cli_refuses_sensitive_or_role_arguments(flag):
    with pytest.raises(SystemExit):
        main(["create-user", "--email", "caue@example.com", "--name", "Caue", flag, "value"])


def test_init_invalid_existing_key_is_not_overwritten(cli_env):
    path = cli_env / "keys" / "auth.pem"
    path.parent.mkdir()
    path.write_bytes(b"invalid")
    assert main(["init"]) != 0
    assert path.read_bytes() == b"invalid"
