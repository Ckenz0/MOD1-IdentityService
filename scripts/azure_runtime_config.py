"""App-scoped release configuration; preserve CORS, identities and private secrets."""

import copy
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def build_secret_patch(app, existing_values, updates):
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
            raise ValueError("Cannot preserve existing secret; aborting")
    for name, value in updates.items():
        if not value:
            raise ValueError("Required deployment secret is empty")
        secrets[name] = {"name": name, "value": value}
    return {
        "location": app["location"],
        "properties": {"configuration": {"secrets": list(secrets.values())}},
    }


def build_runtime_patch(
    app,
    image,
    *,
    service,
    enable_notifications=False,
    resend_from="",
    model="gemini-3.5-flash-lite",
):
    if app["properties"]["configuration"].get("activeRevisionsMode") != "Single":
        raise ValueError("Expected existing single-revision traffic mode")
    match = re.fullmatch(
        r"([a-z0-9]{5,50}\.azurecr\.io)/(identity|projects|backlog)@sha256:[a-f0-9]{64}", image
    )
    registries = {r["server"] for r in app["properties"]["configuration"].get("registries", [])}
    if not match or match[1] not in registries or match[2] != service:
        raise ValueError("Expected immutable image from the service's configured registry")
    if enable_notifications and service != "backlog":
        raise ValueError("Only Backlog has an agreed Module 6 source")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", model):
        raise ValueError("Invalid Gemini model")
    template = copy.deepcopy(app["properties"]["template"])
    template.pop("revisionSuffix", None)
    containers = template["containers"]
    if len(containers) not in {1, 2} or containers[0]["name"] != "api":
        raise ValueError("Unexpected container layout")
    if len(containers) == 2 and not (
        service == "backlog"
        and containers[1].get("name") == "module6-worker"
        and containers[1].get("command") == ["python", "-m", "backlog_service.module6_cli"]
    ):
        raise ValueError("Unexpected sidecar; refusing to overwrite")
    api = containers[0]
    env = {v["name"]: v for v in api.get("env", [])}
    if len(env) != len(api.get("env", [])):
        raise ValueError("Duplicate environment variable names")
    cors = json.loads(env["CORS_ORIGINS"]["value"])
    if (
        not isinstance(cors, list)
        or not cors
        or any(not isinstance(v, str) or v == "*" for v in cors)
    ):
        raise ValueError("Existing explicit CORS origins are required")
    for name, value in {
        "AI_PROVIDER": "gemini",
        "AI_SIMULATED": "false",
        "GEMINI_MODEL": model,
    }.items():
        env[name] = {"name": name, "value": value}
    env["GEMINI_API_KEY"] = {"name": "GEMINI_API_KEY", "secretRef": "gemini-api-key"}
    if service == "identity":
        if not resend_from or any(ord(c) < 32 or ord(c) == 127 for c in resend_from):
            raise ValueError("Verified email sender is required")
        for name, value in {
            "RESEND_FROM": resend_from,
            "LOCAL_MAILBOX_ENABLED": "false",
            "MAIL_PROVIDER": "resend",
        }.items():
            env[name] = {"name": name, "value": value}
    else:
        env["AUTH_SESSION_CHECK_ENABLED"] = {"name": "AUTH_SESSION_CHECK_ENABLED", "value": "true"}
        env["MODULE6_ENABLED"] = {
            "name": "MODULE6_ENABLED",
            "value": "true" if enable_notifications else "false",
        }
    if service == "backlog":
        env["PROJECTS_LEGACY_ACCESS_ENABLED"] = {
            "name": "PROJECTS_LEGACY_ACCESS_ENABLED",
            "value": "false",
        }
        env["CODE_REVIEW_ENABLED"] = {"name": "CODE_REVIEW_ENABLED", "value": "false"}
    api["image"] = image
    if enable_notifications:
        env["MODULE6_SOURCE"] = {"name": "MODULE6_SOURCE", "value": "backlog"}
        env["MODULE6_KEY"] = {"name": "MODULE6_KEY", "secretRef": "module6-key"}
        worker = {
            "name": "module6-worker",
            "image": image,
            "command": ["python", "-m", "backlog_service.module6_cli"],
            "args": ["run", "--batch-size", "50", "--poll-seconds", "10"],
            "resources": {"cpu": 0.25, "memory": "0.5Gi"},
            "env": [
                copy.deepcopy(env[name])
                for name in (
                    "DATABASE_URL",
                    "DATABASE_SCHEMA",
                    "MODULE6_KEY",
                    "MODULE6_ENABLED",
                    "MODULE6_SOURCE",
                )
            ],
        }
        template["containers"] = [api, worker]
        template.setdefault("scale", {})["minReplicas"] = 1
    api["env"] = list(env.values())
    return {"location": app["location"], "properties": {"template": template}}


def azure(*arguments):
    result = subprocess.run(
        ["az", *arguments, "--only-show-errors"], capture_output=True, text=True, timeout=180
    )
    if result.returncode:
        raise RuntimeError("Azure operation failed; inspect scoped resource activity logs")
    return json.loads(result.stdout) if result.stdout.strip() else None


def apply_patch(url, payload):
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as stream:
            path = Path(stream.name)
            json.dump(payload, stream)
        azure(
            "rest", "--method", "patch", "--url", url, "--body", "@" + str(path), "--output", "none"
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def wait_provisioned(url):
    for _ in range(60):
        app = azure("rest", "--method", "get", "--url", url, "--output", "json")
        state = app["properties"].get("provisioningState")
        if state == "Succeeded":
            return app
        if state in {"Failed", "Canceled"}:
            raise RuntimeError("App update failed")
        time.sleep(2)
    raise RuntimeError("App update timed out")


def main():
    subscription = azure("account", "show", "--output", "json")["id"]
    group = os.environ["AZURE_RESOURCE_GROUP"]
    name = os.environ["AZURE_CONTAINER_APP"]
    service = os.environ["IMAGE_REPOSITORY"]
    if (
        not re.fullmatch(r"[a-fA-F0-9-]{36}", subscription)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,90}", group)
        or not re.fullmatch(r"[a-z][a-z0-9-]{1,30}[a-z0-9]", name)
    ):
        raise ValueError("Invalid deployment scope")
    resource = f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.App/containerApps/{name}"
    url = resource + "?api-version=2025-01-01"
    before = azure("rest", "--method", "get", "--url", url, "--output", "json")
    image = os.environ["IMAGE_REFERENCE"]
    options = {
        "service": service,
        "enable_notifications": service == "backlog",
        "resend_from": os.environ.get("RESEND_FROM", ""),
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    }
    build_runtime_patch(before, image, **options)
    updates = {"gemini-api-key": os.environ["GEMINI_API_KEY"]}
    if service == "backlog":
        updates["module6-key"] = os.environ["MODULE6_KEY"]
    existing = azure(
        "rest",
        "--method",
        "post",
        "--url",
        resource + "/listSecrets?api-version=2025-01-01",
        "--output",
        "json",
    )["value"]
    apply_patch(url, build_secret_patch(before, existing, updates))
    current = wait_provisioned(url)
    if current["properties"]["template"] != before["properties"]["template"]:
        raise RuntimeError("Application template changed concurrently; rerun from current state")
    patch = build_runtime_patch(current, image, **options)
    suffix = "rel-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not re.fullmatch(r"rel-[0-9]+-[0-9]+", suffix):
        raise ValueError("Invalid release revision suffix")
    patch["properties"]["template"]["revisionSuffix"] = suffix
    apply_patch(url, patch)
    for _ in range(60):
        final = azure("rest", "--method", "get", "--url", url, "--output", "json")
        p = final["properties"]
        revision = p.get("latestRevisionName", "")
        if revision.endswith("--" + suffix) and p.get("latestReadyRevisionName") == revision:
            host = p["configuration"]["ingress"]["fqdn"]
            if not re.fullmatch(r"[a-z0-9.-]+\.azurecontainerapps\.io", host):
                raise ValueError("Unexpected application hostname")
            try:
                with urlopen("https://" + host + "/health/ready", timeout=15) as response:
                    healthy = response.status == 200
            except OSError:
                healthy = False
            if healthy:
                print(
                    json.dumps(
                        {
                            "service": service,
                            "ready_revision": revision,
                            "image": image,
                            "gemini_enabled": True,
                            "notifications_enabled": service == "backlog",
                        }
                    )
                )
                return
        if p.get("provisioningState") in {"Failed", "Canceled"}:
            raise RuntimeError("New app revision failed")
        time.sleep(5)
    raise RuntimeError("New app revision did not become ready")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit(
            "Runtime release configuration failed; no secret values are written to logs."
        ) from None
