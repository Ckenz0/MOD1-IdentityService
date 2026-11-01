"""Secret deployment must preserve existing configuration and app-scoped IAM."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "azure_identity_secrets.py"


def load_script():
    assert SCRIPT.is_file(), "Missing app-scoped secret deployment helper"
    spec = importlib.util.spec_from_file_location("azure_identity_secrets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_patch_preserves_values_and_key_vault_references():
    module = load_script()
    app = {
        "location": "brazilsouth",
        "properties": {
            "managedEnvironmentId": "/existing/environment",
            "configuration": {
                "ingress": {"external": True},
                "secrets": [
                    {
                        "name": "database",
                        "keyVaultUrl": "https://vault.invalid/db",
                        "identity": "/identity",
                    },
                    {"name": "legacy-native"},
                    {"name": "resend-api-key"},
                ],
            },
            "template": {"scale": {"minReplicas": 0}},
        },
    }
    patch = module.build_patch(
        app,
        [{"name": "legacy-native", "value": "keep-me"}, {"name": "resend-api-key", "value": "old"}],
        {"resend-api-key": "new", "mfa-encryption-key": "mfa"},
    )
    assert set(patch) == {"location", "properties"}
    assert set(patch["properties"]) == {"configuration"}
    assert set(patch["properties"]["configuration"]) == {"secrets"}
    secrets = {item["name"]: item for item in patch["properties"]["configuration"]["secrets"]}
    assert secrets["database"] == app["properties"]["configuration"]["secrets"][0]
    assert secrets["legacy-native"] == {"name": "legacy-native", "value": "keep-me"}
    assert secrets["resend-api-key"] == {"name": "resend-api-key", "value": "new"}
    assert secrets["mfa-encryption-key"] == {"name": "mfa-encryption-key", "value": "mfa"}
    assert "value" not in app["properties"]["configuration"]["secrets"][1]


def test_missing_existing_secret_value_aborts_instead_of_erasing_it():
    module = load_script()
    app = {
        "location": "brazilsouth",
        "properties": {"configuration": {"secrets": [{"name": "database"}]}},
    }
    with pytest.raises(ValueError, match="preserve"):
        module.build_patch(app, [], {"mfa-encryption-key": "new"})
