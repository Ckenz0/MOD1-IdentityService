"""Validate public deployment references before passing them to Azure."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

SECRET_NAMES = {
    "authDatabaseSecretUri": "identity-database-url",
    "projectsDatabaseSecretUri": "projects-database-url",
    "backlogDatabaseSecretUri": "backlog-database-url",
    "jwtKeySecretUri": "identity-jwt-private-key",
}
OPTIONAL_SECRET_NAMES = {
    "authMfaSecretUri": "identity-mfa-encryption-key",
    "authResendSecretUri": "identity-resend-api-key",
}
OPTIONAL_FIELDS = {*OPTIONAL_SECRET_NAMES, "resendFrom"}
IMAGE_NAMES = ("authImage", "projectsImage", "backlogImage")
FIELDS = {
    "resourcePrefix",
    "environmentName",
    "registryName",
    "vaultName",
    "frontendOrigin",
    *SECRET_NAMES,
    *IMAGE_NAMES,
}


def write_parameters(values: dict[str, str], destination: Path) -> None:
    if not FIELDS <= set(values) <= FIELDS | OPTIONAL_FIELDS or any(
        not isinstance(v, str) for v in values.values()
    ):
        raise ValueError("Expected the documented deployment reference fields")
    patterns = {
        "resourcePrefix": r"[a-z][a-z0-9-]{2,14}",
        "environmentName": r"[a-z][a-z0-9-]{2,31}",
        "registryName": r"[a-z0-9]{5,50}",
        "vaultName": r"[a-z][a-z0-9-]{1,22}[a-z0-9]",
    }
    for field, pattern in patterns.items():
        if not re.fullmatch(pattern, values[field]):
            raise ValueError(f"Invalid {field}")
    origin = values["frontendOrigin"]
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "\\" in origin
        or any(c.isspace() or ord(c) < 32 for c in origin)
    ):
        raise ValueError("Invalid frontendOrigin: expected an exact HTTPS origin")
    try:
        _ = parsed.port
    except ValueError:
        raise ValueError("Invalid frontendOrigin port") from None
    for field in IMAGE_NAMES:
        if not re.fullmatch(
            re.escape(values["registryName"])
            + r"\.azurecr\.io/[a-z0-9]+(?:[._/-][a-z0-9]+)*@sha256:[a-f0-9]{64}",
            values[field],
        ):
            raise ValueError(f"Invalid {field}: expected an immutable image in this registry")
    for field, secret_name in (SECRET_NAMES | OPTIONAL_SECRET_NAMES).items():
        if field in OPTIONAL_SECRET_NAMES and not values.get(field):
            continue
        expected = f"https://{values['vaultName']}.vault.azure.net/secrets/{secret_name}/"
        if not re.fullmatch(re.escape(expected) + r"[a-f0-9]{32}", values[field]):
            raise ValueError(f"Invalid {field}: expected its versioned secret in this vault")
    sender = values.get("resendFrom", "")
    if bool(values.get("authResendSecretUri")) != bool(sender):
        raise ValueError("Configure the Resend secret reference and sender together")
    if sender and (not sender.strip() or any(ord(c) < 32 or ord(c) == 127 for c in sender)):
        raise ValueError("Invalid Resend sender")
    content = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {key: {"value": value} for key, value in values.items()},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(content, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        values = json.loads(args.references.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("Expected an object of deployment references")
        write_parameters(values, args.output)
    except (ValueError, OSError):
        parser.exit(2, "Invalid deployment references; see the documented schema.\n")


if __name__ == "__main__":
    main()
