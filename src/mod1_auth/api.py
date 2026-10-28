from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mod1_auth.database import database_is_ready
from mod1_auth.domain import (
    DuplicateEmailError,
    InvalidCredentialsError,
    PasswordChangeRejectedError,
    User,
)
from mod1_auth.profile_repository import ProfileRepository
from mod1_auth.profile_service import ProfileService
from mod1_auth.profiles import Profile, ProfilePatch
from mod1_auth.repositories import UserRepository
from mod1_auth.security import TokenResponse, build_jwks
from mod1_auth.services import AuthService, UserService, normalize_email

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        try:
            validate_email(normalized, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError("Invalid email address") from exc
        return normalized

    @field_validator("display_name", mode="before")
    @classmethod
    def trimmed_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("display_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class RegistrationResponse(BaseModel):
    message: str = "If this email is available, the account is ready. Try signing in."


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    current_password: str = Field(max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


class PasswordPolicyResponse(BaseModel):
    min_length: int
    max_length: int = 128


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_active=user.is_active,
            created_at=user.created_at,
        )


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


def authenticated_profile_token(token: Annotated[str | None, Depends(oauth2)]) -> str:
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def register_routes(app: FastAPI) -> None:
    profile_responses: dict[int | str, dict[str, Any]] = {
        401: {"description": "Invalid authentication credentials"},
        422: {"description": "Invalid profile data"},
        503: {"description": "Service unavailable"},
    }

    @app.get("/auth/profile", response_model=Profile, responses=profile_responses)
    def profile(
        token: Annotated[str, Depends(authenticated_profile_token)],
        service: Annotated[ProfileService, Depends(get_profile_service)],
    ) -> Profile:
        try:
            return service.get(token)
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @app.patch("/auth/profile", response_model=Profile, responses=profile_responses)
    def patch_profile(
        patch: ProfilePatch,
        token: Annotated[str, Depends(authenticated_profile_token)],
        service: Annotated[ProfileService, Depends(get_profile_service)],
    ) -> Profile:
        try:
            return service.patch(token, patch)
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @app.post("/auth/register", status_code=202, response_model=RegistrationResponse)
    def register(
        response: Response,
        registration: RegistrationRequest,
        service: Annotated[UserService, Depends(get_user_service)],
    ) -> RegistrationResponse:
        try:
            service.create_user(
                email=registration.email,
                display_name=registration.display_name,
                password=registration.password,
            )
        except DuplicateEmailError:
            # Same response for existing accounts; never overwrite or reactivate them.
            pass
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "type": "value_error",
                        "loc": ["body", "password"],
                        "msg": "Password does not meet the configured length policy",
                    }
                ],
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return RegistrationResponse()

    @app.get("/auth/password-policy", response_model=PasswordPolicyResponse)
    def password_policy(request: Request) -> PasswordPolicyResponse:
        return PasswordPolicyResponse(min_length=request.app.state.password_min_length)

    @app.post(
        "/auth/password",
        status_code=204,
        responses={
            400: {"description": "Password change rejected"},
            401: {"description": "Invalid authentication credentials"},
            503: {"description": "Service unavailable"},
        },
    )
    def change_password(
        change: PasswordChangeRequest,
        token: Annotated[str | None, Depends(oauth2)],
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> Response:
        try:
            if not token:
                raise InvalidCredentialsError()
            service.change_password(token, change.current_password, change.new_password)
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except PasswordChangeRejectedError as exc:
            raise HTTPException(status_code=400, detail="Password change rejected") from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "type": "value_error",
                        "loc": ["body", "new_password"],
                        "msg": "Password does not meet the configured length policy",
                    }
                ],
            ) from exc
        return Response(status_code=204)

    @app.post(
        "/auth/token",
        response_model=TokenResponse,
        responses={401: {"description": "Invalid credentials"}},
    )
    def token(
        response: Response,
        form: Annotated[OAuth2PasswordRequestForm, Depends()],
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> TokenResponse:
        try:
            result = service.authenticate(form.username, form.password)
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.get(
        "/auth/me",
        response_model=UserResponse,
        responses={401: {"description": "Invalid authentication credentials"}},
    )
    def me(
        token: Annotated[str | None, Depends(oauth2)],
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> UserResponse:
        try:
            if not token:
                raise InvalidCredentialsError()
            return UserResponse.from_user(service.current_user(token))
        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @app.get("/.well-known/jwks.json")
    def jwks(request: Request) -> dict[str, list[dict[str, str]]]:
        return build_jwks(request.app.state.keys)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", responses={503: {"description": "Database unavailable"}})
    def ready(request: Request, response: Response) -> dict[str, str]:
        if not database_is_ready(request.app.state.engine):
            response.status_code = 503
            return {"status": "unavailable"}
        return {"status": "ready"}
