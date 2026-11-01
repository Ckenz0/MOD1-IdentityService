"""HTTP contracts only; identity rules live in application services."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from mod1_auth.ai_adapter import AIAdapter
from mod1_auth.api import authenticated_profile_token
from mod1_auth.dependencies import get_ai_adapter, get_auth_service, get_profile_service
from mod1_auth.profile_service import ProfileService
from mod1_auth.recommendation_service import RecommendationService
from mod1_auth.services import AuthService

Auth = Annotated[AuthService, Depends(get_auth_service)]
Bearer = Annotated[str, Depends(authenticated_profile_token)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Profiles = Annotated[ProfileService, Depends(get_profile_service)]


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RecommendationRequest(EmptyRequest):
    kind: Literal["access_anomalies"]
    constraints: dict[str, Any] = Field(default_factory=dict)


class DecisionRequest(EmptyRequest):
    expected_version: int = Field(ge=1)


class RefreshRequest(EmptyRequest):
    refresh_token: str = Field(min_length=1, max_length=512, repr=False)


class ActiveRequest(EmptyRequest):
    is_active: bool


class JtiRequest(EmptyRequest):
    jti: UUID = Field(strict=False)


class EmailRequest(EmptyRequest):
    email: str = Field(min_length=1, max_length=320)


class ProvisionRequest(EmailRequest):
    display_name: str = Field(min_length=1, max_length=120)


class TokenRequest(EmptyRequest):
    token: str = Field(min_length=1, max_length=512, repr=False)


class ResetRequest(TokenRequest):
    new_password: str = Field(min_length=12, max_length=128, repr=False)
    second_factor: str | None = Field(default=None, max_length=6, repr=False)
    recovery_code: str | None = Field(default=None, max_length=128, repr=False)


class PasswordRequest(EmptyRequest):
    password: str = Field(max_length=128, repr=False)


class CodeRequest(EmptyRequest):
    code: str = Field(min_length=6, max_length=6, repr=False)


class ChallengeRequest(EmptyRequest):
    challenge_token: str = Field(min_length=1, max_length=512, repr=False)
    code: str | None = Field(default=None, max_length=6, repr=False)
    recovery_code: str | None = Field(default=None, max_length=128, repr=False)


class ManageMfaRequest(PasswordRequest):
    code: str | None = Field(default=None, max_length=6, repr=False)
    recovery_code: str | None = Field(default=None, max_length=128, repr=False)


class RegenerateCodesRequest(PasswordRequest):
    code: str = Field(min_length=6, max_length=6, repr=False)


def register_identity_routes(app: FastAPI) -> None:
    @app.post("/admin/recommendations", status_code=201)
    def recommend(
        body: RecommendationRequest,
        token: Bearer,
        service: Auth,
        adapter: Annotated[AIAdapter, Depends(get_ai_adapter)],
    ) -> dict[str, Any]:
        return RecommendationService(service.identity, adapter.generate).create(token)

    @app.get("/admin/recommendations")
    def recommendations(
        token: Bearer, service: Auth, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return RecommendationService(service.identity, lambda _: {}).list(token, limit, offset)

    @app.get("/admin/recommendations/{rid}")
    def recommendation(rid: UUID, token: Bearer, service: Auth) -> dict[str, Any]:
        return RecommendationService(service.identity, lambda _: {}).get(token, rid)

    @app.post("/admin/recommendations/{rid}/approve")
    def approve(rid: UUID, body: DecisionRequest, token: Bearer, service: Auth) -> dict[str, Any]:
        return RecommendationService(service.identity, lambda _: {}).decide(
            token, rid, body.expected_version, True
        )

    @app.post("/admin/recommendations/{rid}/reject")
    def reject(rid: UUID, body: DecisionRequest, token: Bearer, service: Auth) -> dict[str, Any]:
        return RecommendationService(service.identity, lambda _: {}).decide(
            token, rid, body.expected_version, False
        )

    @app.get("/auth/directory")
    def directory(
        token: Bearer, service: Profiles, q: str = "", limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.directory(token, q, limit, offset)

    @app.get("/auth/directory/{user_id}")
    def snapshot(user_id: UUID, token: Bearer, service: Profiles) -> dict[str, Any]:
        return service.snapshot(token, user_id)

    @app.post("/auth/password/reset/request", status_code=202)
    def request_reset(body: EmailRequest, service: Auth) -> dict[str, str]:
        service.credentials.request_reset(body.email)
        return {"message": "If eligible, instructions will be sent."}

    @app.post("/auth/password/reset/confirm", status_code=204)
    def confirm_reset(body: ResetRequest, service: Auth) -> Response:
        service.credentials.confirm_reset(
            body.token, body.new_password, body.second_factor, body.recovery_code
        )
        return Response(status_code=204)

    @app.post("/auth/email/request", status_code=202)
    def request_email(body: EmptyRequest, token: Bearer, service: Auth) -> dict[str, str]:
        service.credentials.request_email(token)
        return {"message": "If eligible, instructions will be sent."}

    @app.post("/auth/email/confirm", status_code=204)
    def confirm_email(body: TokenRequest, service: Auth) -> Response:
        service.credentials.confirm_email(body.token)
        return Response(status_code=204)

    @app.get("/auth/mfa")
    def mfa(token: Bearer, service: Auth) -> dict[str, bool]:
        return service.credentials.mfa_state(token)

    @app.post("/auth/mfa/setup")
    def setup(body: PasswordRequest, token: Bearer, service: Auth) -> dict[str, str]:
        return service.credentials.setup(token, body.password)

    @app.post("/auth/mfa/enable")
    def enable(body: CodeRequest, token: Bearer, service: Auth) -> dict[str, list[str]]:
        return service.credentials.enable(token, body.code)

    @app.post("/auth/mfa/verify")
    def verify_mfa(body: ChallengeRequest, service: Auth) -> Any:
        return service.credentials.verify_challenge(
            body.challenge_token, body.code, body.recovery_code
        )

    @app.post("/auth/mfa/recovery-codes")
    def recovery_codes(body: RegenerateCodesRequest, token: Bearer, service: Auth) -> Any:
        return service.credentials.manage(token, body.password, body.code, None)

    @app.post("/auth/mfa/disable", status_code=204)
    def disable_mfa(body: ManageMfaRequest, token: Bearer, service: Auth) -> Response:
        service.credentials.manage(
            token, body.password, body.code, body.recovery_code, disable=True
        )
        return Response(status_code=204)

    @app.get("/admin/mailbox")
    def mailbox(
        token: Bearer, service: Auth, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.credentials.mailbox(token, limit, offset)

    @app.post("/admin/users", status_code=202)
    def provision(body: ProvisionRequest, token: Bearer, service: Auth) -> dict[str, str]:
        service.credentials.provision(token, body.email, body.display_name)
        return {"message": "If eligible, setup instructions will be sent."}

    @app.post("/auth/refresh")
    def refresh(body: RefreshRequest, service: Auth) -> Any:
        return service.identity.refresh(body.refresh_token)

    @app.post("/auth/logout", status_code=204)
    def logout(body: EmptyRequest, token: Bearer, service: Auth) -> Response:
        service.identity.logout(token)
        return Response(status_code=204)

    @app.get("/auth/sessions")
    def sessions(
        token: Bearer, service: Auth, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.identity.list_sessions(token, limit, offset)

    @app.delete("/auth/sessions/{sid}", status_code=204)
    def revoke_session(sid: UUID, token: Bearer, service: Auth) -> Response:
        service.identity.revoke(token, sid)
        return Response(status_code=204)

    @app.post("/auth/sessions/revoke-all", status_code=204)
    def revoke_all(body: EmptyRequest, token: Bearer, service: Auth) -> Response:
        service.identity.revoke(token, all_sessions=True)
        return Response(status_code=204)

    @app.post("/auth/session/activity")
    def activity(body: EmptyRequest, token: Bearer, service: Auth) -> dict[str, Any]:
        return service.identity.activity(token)

    @app.get("/auth/audit")
    def audit(
        token: Bearer, service: Auth, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.identity.audit(token, limit, offset)

    @app.get("/auth/users/{user_id}/status")
    def user_status(user_id: UUID, token: Bearer, service: Auth) -> dict[str, Any]:
        return service.identity.user_status(token, user_id)

    @app.get("/admin/users")
    def users(
        token: Bearer, service: Auth, q: str = "", limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.identity.list_users(token, q, limit, offset)

    @app.get("/admin/audit")
    def admin_audit(
        token: Bearer, service: Auth, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        return service.identity.audit(token, limit, offset, admin=True)

    @app.patch("/admin/users/{user_id}")
    def active(user_id: UUID, body: ActiveRequest, token: Bearer, service: Auth) -> dict[str, Any]:
        return service.identity.admin_action(token, user_id, "active", body.is_active)

    @app.post("/admin/users/{user_id}/unlock", status_code=204)
    def unlock(user_id: UUID, body: EmptyRequest, token: Bearer, service: Auth) -> Response:
        service.identity.admin_action(token, user_id, "unlock")
        return Response(status_code=204)

    @app.post("/admin/users/{user_id}/revoke-sessions", status_code=204)
    def admin_revoke(user_id: UUID, body: EmptyRequest, token: Bearer, service: Auth) -> Response:
        service.identity.admin_action(token, user_id, "revoke")
        return Response(status_code=204)

    @app.post("/admin/tokens/revoke", status_code=204)
    def revoke_jti(body: JtiRequest, token: Bearer, service: Auth) -> Response:
        service.identity.revoke_jti(token, body.jti)
        return Response(status_code=204)
