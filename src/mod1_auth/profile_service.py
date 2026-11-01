from typing import Any
from uuid import UUID

from mod1_auth.identity_service import IdentityError, page
from mod1_auth.profile_repository import ProfileRepository
from mod1_auth.profiles import Profile, ProfilePatch
from mod1_auth.services import AuthService


class ProfileService:
    def __init__(self, profiles: ProfileRepository, auth: AuthService) -> None:
        self.profiles = profiles
        self.auth = auth

    def get(self, token: str) -> Profile:
        return self.profiles.get(self.auth.current_user(token).id)

    def patch(self, token: str, patch: ProfilePatch) -> Profile:
        return self.profiles.patch(self.auth.current_user(token).id, patch)

    def directory(self, token: str, q: str, limit: int, offset: int) -> dict[str, Any]:
        self.auth.current_user(token)
        snapshots = [
            item
            for item in self.profiles.snapshots()
            if item["share_for_recommendations"]
            and q.casefold()
            in (
                item["display_name"]
                + " "
                + item["summary"]
                + " "
                + " ".join(skill["name"] for skill in item["skills"])
            ).casefold()
        ]
        return page(snapshots, limit, offset)

    def snapshot(self, token: str, user_id: UUID) -> dict[str, Any]:
        actor = self.auth.current_user(token)
        for item in self.profiles.snapshots():
            if item["user_id"] == str(user_id):
                if (
                    item["share_for_recommendations"]
                    or actor.id == user_id
                    or self.auth.identity.flags(actor)["is_admin"]
                ):
                    return item
        raise IdentityError(404, "Profile unavailable")
