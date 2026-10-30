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
