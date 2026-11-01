"""HTTP composition: request-scoped services and infrastructure dependencies."""

from collections.abc import Iterator

from fastapi import Request

from mod1_auth.ai_adapter import AIAdapter
from mod1_auth.database import database_is_ready
from mod1_auth.profile_repository import ProfileRepository
from mod1_auth.profile_service import ProfileService
from mod1_auth.repositories import UserRepository
from mod1_auth.services import AuthService, UserService


def get_auth_service(request: Request) -> Iterator[AuthService]:
    with request.app.state.sessions() as session:
        yield AuthService(
            UserRepository(session), request.app.state.tokens, request.app.state.password_min_length
        )


def get_user_service(request: Request) -> Iterator[UserService]:
    with request.app.state.sessions() as session:
        yield UserService(UserRepository(session), request.app.state.password_min_length)


def get_profile_service(request: Request) -> Iterator[ProfileService]:
    with request.app.state.sessions() as session:
        yield ProfileService(
            ProfileRepository(session),
            AuthService(UserRepository(session), request.app.state.tokens),
        )


def get_database_readiness(request: Request) -> bool:
    return database_is_ready(request.app.state.engine)


def get_ai_adapter(request: Request) -> AIAdapter:
    return AIAdapter(request.app.state.tokens.settings)
