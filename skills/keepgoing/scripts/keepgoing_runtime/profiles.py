"""Framework profile definitions and safe path policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .errors import KeepgoingError, INVALID


STANDARD_CONTAINERS = (
    ".github/workflows",
    "apps",
    "packages",
    "apis",
    "sql",
    "tests",
    "config",
    "scripts",
    "docs",
    "infra",
    "storage",
)


PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "application_roots": ["Project/apps/api"],
        "native_paths": ["Project/apps/api/src", "Project/apps/api/tests"],
        "entrypoints": ["Project/apps/api"],
        "summary": "Generic backend under apps/api with local source and tests.",
    },
    "angular": {
        "application_roots": ["Project/apps/web"],
        "native_paths": [
            "Project/apps/web/public",
            "Project/apps/web/src/app/core/auth",
            "Project/apps/web/src/app/core/http",
            "Project/apps/web/src/app/core/config",
            "Project/apps/web/src/app/shared/components",
            "Project/apps/web/src/app/shared/directives",
            "Project/apps/web/src/app/shared/pipes",
            "Project/apps/web/src/app/features",
        ],
        "entrypoints": [
            "Project/apps/web/src/index.html",
            "Project/apps/web/src/main.ts",
            "Project/apps/web/src/styles.scss",
            "Project/apps/web/src/app/app.config.ts",
            "Project/apps/web/src/app/app.routes.ts",
            "Project/apps/web/angular.json",
            "Project/apps/web/package.json",
            "Project/apps/web/tsconfig.json",
        ],
        "summary": "Angular application under apps/web using core, shared, and feature ownership.",
    },
    "flutter": {
        "application_roots": ["Project/apps/flutter_app"],
        "native_paths": [
            "Project/apps/flutter_app/lib/core",
            "Project/apps/flutter_app/lib/features",
            "Project/apps/flutter_app/lib/shared",
            "Project/apps/flutter_app/test",
            "Project/apps/flutter_app/integration_test",
            "Project/apps/flutter_app/assets",
        ],
        "entrypoints": [
            "Project/apps/flutter_app/lib/main.dart",
            "Project/apps/flutter_app/pubspec.yaml",
            "Project/apps/flutter_app/analysis_options.yaml",
        ],
        "summary": "Flutter application under apps/flutter_app with feature data/domain/presentation boundaries.",
    },
    "php": {
        "application_roots": ["Project/apps/web"],
        "native_paths": [
            "Project/apps/web/public",
            "Project/apps/web/src",
            "Project/apps/web/config",
            "Project/apps/web/tests",
        ],
        "entrypoints": [
            "Project/apps/web/public/index.php",
            "Project/apps/web/composer.json",
        ],
        "summary": "Pure PHP web application with public as the only document root.",
    },
}


def normalize_relative_path(value: str) -> str:
    value = value.replace("\\", "/").strip()
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise KeepgoingError(f"Unsafe relative path: {value!r}", INVALID)
    normalized = str(path)
    if normalized == "." or not normalized.startswith("Project/"):
        raise KeepgoingError(
            f"Application paths must be inside Project/: {value!r}", INVALID
        )
    return normalized


def get_profile(name: str) -> dict[str, Any]:
    key = name.lower().strip()
    if key not in PROFILES:
        raise KeepgoingError(
            f"Unknown profile {name!r}; choose one of {', '.join(sorted(PROFILES))}",
            INVALID,
        )
    return PROFILES[key]


def profile_allows(profile_name: str, value: str) -> bool:
    normalized = normalize_relative_path(value)
    profile = get_profile(profile_name)
    return any(
        normalized == root or normalized.startswith(root + "/")
        for root in profile["application_roots"]
    ) or any(
        normalized == "Project/" + container
        or normalized.startswith("Project/" + container + "/")
        for container in STANDARD_CONTAINERS
        if container not in {"apps"}
    )
