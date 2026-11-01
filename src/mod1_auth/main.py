from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint

from mod1_auth.api import register_routes
from mod1_auth.config import Settings
from mod1_auth.database import create_engine_for_url, create_session_factory
from mod1_auth.domain import InvalidCredentialsError
from mod1_auth.identity_api import register_identity_routes
from mod1_auth.identity_service import IdentityError
from mod1_auth.security import TokenService, load_key_material


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            keys = load_key_material(configuration.jwt_private_key_path)
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("JWT key unavailable or invalid; run administrative init") from exc
        engine = create_engine_for_url(
            configuration.database_url.get_secret_value(), schema=configuration.database_schema
        )
        app.state.keys = keys
        app.state.tokens = TokenService(keys, configuration)
        app.state.engine = engine
        app.state.sessions = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Módulo 1 — Autenticação", version=version("mod1-auth"), lifespan=lifespan)
    app.state.password_min_length = configuration.password_min_length
    if configuration.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=configuration.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Service unavailable"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        # FastAPI's default validation response includes input values, including passwords.
        errors = [
            {"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(InvalidCredentialsError)
    async def credentials_error(request: Request, exc: InvalidCredentialsError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid authentication credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(IdentityError)
    async def identity_error(request: Request, exc: IdentityError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.middleware("http")
    async def password_no_store(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(("/auth/", "/admin/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    register_routes(app)
    register_identity_routes(app)
    return app
