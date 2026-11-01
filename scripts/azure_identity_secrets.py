"""Patch only app secrets; never resend environment bindings or print secrets."""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path


def build_patch(app, existing_values, updates):
    values = {item["name"]: item for item in existing_values}
    secrets = {}
    for original in app["properties"]["configuration"].get("secrets", []):
        name = original["name"]
        if name in updates:
            continue
        if original.get("keyVaultUrl"):
            secrets[name] = {
                key: original[key] for key in ("name", "keyVaultUrl", "identity") if key in original
            }
        elif "value" in values.get(name, {}):
            secrets[name] = {"name": name, "value": values[name]["value"]}
        else:
            raise ValueError("Cannot preserve an existing native secret; aborting")
    for name, value in updates.items():
        if not value:
            raise ValueError("Required deployment secret is empty")
        secrets[name] = {"name": name, "value": value}
    return {
        "location": app["location"],
        "properties": {"configuration": {"secrets": list(secrets.values())}},
    }


def azure(*arguments):
    result = subprocess.run(
        ["az", *arguments, "--only-show-errors"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        # Provider responses can echo submitted data. Keep them out of CI logs.
        raise RuntimeError("Azure secret operation failed; inspect resource activity logs")
    return json.loads(result.stdout) if result.stdout.strip() else None


def main():
    subscription = azure("account", "show", "--output", "json")["id"]
    group = os.environ["AZURE_RESOURCE_GROUP"]
    name = os.environ["AZURE_CONTAINER_APP"]
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", subscription):
        raise ValueError("Invalid subscription identifier")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,90}", group):
        raise ValueError("Invalid resource group")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}[a-z0-9]", name):
        raise ValueError("Invalid Container App name")
    resource = (
        f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/containerApps/{name}"
    )
    url = resource + "?api-version=2025-01-01"
    app = azure("rest", "--method", "get", "--url", url, "--output", "json")
    current = azure(
        "rest",
        "--method",
        "post",
        "--url",
        resource + "/listSecrets?api-version=2025-01-01",
        "--output",
        "json",
    )["value"]
    patch = build_patch(
        app,
        current,
        {
            "mfa-encryption-key": os.environ["MFA_ENCRYPTION_KEY"],
            "resend-api-key": os.environ["RESEND_API_KEY"],
        },
    )
    # NamedTemporaryFile is owner-only on the Linux runner. Only its path enters argv.
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as payload:
            path = Path(payload.name)
            json.dump(patch, payload)
        azure(
            "rest", "--method", "patch", "--url", url, "--body", "@" + str(path), "--output", "none"
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
    for _ in range(60):
        status = azure("rest", "--method", "get", "--url", url, "--output", "json")
        state = status["properties"].get("provisioningState")
        if state == "Succeeded":
            print("App secrets updated; existing configuration preserved.")
            return
        if state in {"Failed", "Canceled"}:
            raise RuntimeError("Secret update did not succeed")
        time.sleep(2)
    raise RuntimeError("Timed out waiting for secret update")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit("Secret update failed; no secret values are written to logs.") from None
