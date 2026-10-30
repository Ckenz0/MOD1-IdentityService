import argparse
import getpass
import sys
from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from mod1_auth.config import Settings
from mod1_auth.database import create_engine_for_url, create_session_factory, initialize_database
from mod1_auth.domain import DuplicateEmailError, UserNotFoundError
from mod1_auth.repositories import UserRepository
from mod1_auth.security import generate_private_key, load_key_material
from mod1_auth.services import UserService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administracao local da autenticacao")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Preparar schema e chave persistente")
    create = commands.add_parser("create-user", help="Criar conta individual")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    toggle = commands.add_parser("set-active", help="Ativar ou desativar conta")
    toggle.add_argument("--user-id", type=UUID, required=True)
    active = toggle.add_mutually_exclusive_group(required=True)
    active.add_argument("--active", dest="active", action="store_true")
    active.add_argument("--inactive", dest="active", action="store_false")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
        engine = create_engine_for_url(
            settings.database_url.get_secret_value(), schema=settings.database_schema
        )
        try:
            if args.command == "init":
                try:
                    generate_private_key(settings.jwt_private_key_path)
                except FileExistsError:
                    pass
                load_key_material(settings.jwt_private_key_path)
                initialize_database(engine)
                print("Schema e chave prontos; dados existentes preservados.")
                return 0
            with create_session_factory(engine)() as session:
                users = UserService(UserRepository(session), settings.password_min_length)
                if args.command == "create-user":
                    password = getpass.getpass(
                        f"Senha ({settings.password_min_length} a 128 caracteres): "
                    )
                    confirmation = getpass.getpass("Confirme a senha: ")
                    if password != confirmation:
                        raise ValueError("Password confirmation does not match")
                    user = users.create_user(
                        email=args.email, display_name=args.name, password=password
                    )
                else:
                    user = users.set_user_active(args.user_id, args.active)
                print(f"id={user.id} email={user.email} active={user.is_active}")
                return 0
        finally:
            engine.dispose()
    except ValidationError:
        print("Configuracao invalida; confira as variaveis do ambiente.", file=sys.stderr)
    except (OSError, SQLAlchemyError):
        print(
            "Banco ou chave indisponivel; confira a configuracao e execute init.", file=sys.stderr
        )
    except (ValueError, DuplicateEmailError, UserNotFoundError):
        print(
            "Operacao recusada; confira dados, senha, duplicidade e ID do usuario.", file=sys.stderr
        )
    except (EOFError, KeyboardInterrupt):
        print("Operacao cancelada.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
