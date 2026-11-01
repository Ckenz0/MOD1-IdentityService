"""TOTP RFC 6238 and authenticated encryption infrastructure."""

import base64
import hashlib
import hmac
import secrets
import struct

from cryptography.fernet import Fernet, InvalidToken

from mod1_auth.config import Settings


class CredentialKeyError(Exception):
    pass


def cipher(settings: Settings) -> Fernet:
    try:
        if not settings.mfa_encryption_key:
            raise ValueError()
        return Fernet(settings.mfa_encryption_key.get_secret_value().encode())
    except (ValueError, TypeError) as exc:
        raise CredentialKeyError() from exc


def create_seed(settings: Settings) -> tuple[str, str]:
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    return secret, cipher(settings).encrypt(secret.encode()).decode()


def totp_step(
    settings: Settings, encrypted: str, code: str, now: float, last_step: int = -1
) -> int | None:
    try:
        seed = base64.b32decode(cipher(settings).decrypt(encrypted.encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CredentialKeyError() from exc
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(now // 30)
    for step in (current, current - 1, current + 1):
        if step <= last_step or step < 0:
            continue
        data = hmac.new(seed, struct.pack(">Q", step), hashlib.sha1).digest()
        offset = data[-1] & 15
        number = (struct.unpack(">I", data[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000
        if hmac.compare_digest(str(number).zfill(6), code):
            return step
    return None
