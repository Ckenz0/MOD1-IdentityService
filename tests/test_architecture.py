"""Executable dependency rules for the pragmatic layered architecture."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "mod1_auth"


def imported_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = f"mod1_auth.{module}".rstrip(".")
            for alias in node.names:
                yield f"{module}.{alias.name}"


def belongs_to(name, modules):
    return any(name == module or name.startswith(f"{module}.") for module in modules)


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        (
            module,
            (
                "fastapi",
                "starlette",
                "sqlalchemy",
                "httpx",
                "mod1_auth.api",
                "mod1_auth.dependencies",
                "mod1_auth.main",
                "mod1_auth.config",
                "mod1_auth.database",
                "mod1_auth.repositories",
                "mod1_auth.profile_repository",
                "mod1_auth.security",
                "mod1_auth.services",
                "mod1_auth.profile_service",
            ),
        )
        for module in ("domain", "profiles", "recommendations")
    ]
    + [
        (
            module,
            (
                "fastapi",
                "starlette",
                "sqlalchemy",
                "mod1_auth.api",
                "mod1_auth.dependencies",
                "mod1_auth.main",
                "mod1_auth.database",
                "mod1_auth.repositories.UserRecord",
                "mod1_auth.profile_repository.ProfileRecord",
            ),
        )
        for module in (
            "services",
            "profile_service",
            "identity_service",
            "credential_service",
            "recommendation_service",
        )
    ]
    + [
        (
            "api",
            (
                "sqlalchemy",
                "mod1_auth.database",
                "mod1_auth.repositories",
                "mod1_auth.profile_repository",
            ),
        ),
        (
            "identity_api",
            (
                "sqlalchemy",
                "mod1_auth.database",
                "mod1_auth.repositories",
                "mod1_auth.profile_repository",
                "mod1_auth.identity_repository",
            ),
        ),
        ("security", ("fastapi", "starlette", "mod1_auth.api", "mod1_auth.dependencies")),
        (
            "resend_adapter",
            (
                "fastapi",
                "sqlalchemy",
                "mod1_auth.database",
                "mod1_auth.repositories",
                "mod1_auth.identity_repository",
                "mod1_auth.credential_service",
            ),
        ),
    ],
)
def test_layer_dependencies(module, forbidden):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    violations = [name for name in imported_names(tree) if belongs_to(name, forbidden)]
    assert not violations, f"{module} crosses its layer boundary: {violations}"


@pytest.mark.parametrize("module", ["api", "identity_api"])
def test_routes_do_not_open_sessions_or_execute_database_operations(module):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    violations = [
        f"{node.attr} at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"sessions", "engine", "execute", "query", "commit", "rollback"}
    ]
    assert not violations, f"Routes own persistence operations: {violations}"
