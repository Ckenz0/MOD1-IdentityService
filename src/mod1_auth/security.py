import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pwdlib import PasswordHash
from pydantic import BaseModel

from mod1_auth.config import Settings

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hasher.verify(password, password_hash)


@dataclass(frozen=True)
class KeyMaterial:
    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey
    kid: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    session_id: UUID | None = None
    idle_expires_at: datetime | None = None
    absolute_expires_at: datetime | None = None


@dataclass(frozen=True)
class TokenClaims:
    sub: UUID
    iss: str
    aud: str
    iat: int
    exp: int
    jti: UUID
    sid: UUID | None = None


class TokenValidationError(Exception):
    pass


def generate_private_key(path: Path) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    data = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def load_key_material(path: Path) -> KeyMaterial:
    private = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 3072:
        raise ValueError("An RSA private key of at least 3072 bits is required")
    public = private.public_key()
    der = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return KeyMaterial(private, public, hashlib.sha256(der).hexdigest())


def build_jwks(keys: KeyMaterial) -> dict[str, list[dict[str, str]]]:
    numbers = keys.public_key.public_numbers()

    def encode_number(number: int) -> str:
        return (
            base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big"))
            .rstrip(b"=")
            .decode("ascii")
        )

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": keys.kid,
                "n": encode_number(numbers.n),
                "e": encode_number(numbers.e),
            }
        ]
    }


class TokenService:
    def __init__(self, keys: KeyMaterial, settings: Settings) -> None:
        self.keys = keys
        self.settings = settings

    def issue(
        self, user_id: UUID, now: datetime | None = None, *, session_id: UUID | None = None
    ) -> TokenResponse:
        issued = int((now or datetime.now(UTC)).timestamp())
        ttl = self.settings.access_token_expire_minutes * 60
        claims = {
            "sub": str(user_id),
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "iat": issued,
            "exp": issued + ttl,
            "jti": str(uuid4()),
        }
        if session_id is not None:
            claims["sid"] = str(session_id)
        token = jwt.encode(
            claims,
            self.keys.private_key,
            algorithm="RS256",
            headers={"kid": self.keys.kid, "typ": "JWT"},
        )
        return TokenResponse(access_token=token, expires_in=ttl)

    def verify(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or header.get("kid") != self.keys.kid
            ):
                raise ValueError("Invalid token header")
            claims = jwt.decode(
                token,
                self.keys.public_key,
                algorithms=["RS256"],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                leeway=5,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "jti"], "strict_aud": True},
            )
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or claims["exp"] <= claims["iat"]
            ):
                raise ValueError("Invalid token timestamps")
            return TokenClaims(
                UUID(claims["sub"]),
                claims["iss"],
                claims["aud"],
                claims["iat"],
                claims["exp"],
                UUID(claims["jti"]),
                UUID(claims["sid"]) if claims.get("sid") is not None else None,
            )
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
            raise TokenValidationError("Invalid authentication token") from exc
