import re

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.schema import CreateSchema


class Base(DeclarativeBase):
    pass


def create_engine_for_url(url: str, *, schema: str | None = None) -> Engine:
    if schema is not None and not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError("Invalid database schema")
    if url.startswith("sqlite:///"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
        target_schema = None
    else:
        engine = create_engine(
            url,
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
        target_schema = schema or "mod1_identity"
    return engine.execution_options(schema_translate_map={"mod1_identity": target_schema})


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(engine: Engine) -> None:
    from mod1_auth import (
        profile_repository,  # noqa: F401 -- explicit administrative schema
        repositories,  # noqa: F401 -- register ORM tables for explicit admin init
    )

    if engine.dialect.name == "postgresql":
        schema = engine.get_execution_options()["schema_translate_map"]["mod1_identity"]
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema, if_not_exists=True))
    Base.metadata.create_all(engine)


def database_is_ready(engine: Engine) -> bool:
    from mod1_auth.repositories import UserRecord

    try:
        with engine.connect() as connection:
            connection.execute(select(UserRecord.id).limit(1))
        return True
    except SQLAlchemyError:
        return False
