#!/usr/bin/env python3
"""Static checks that Docker packaging is deploy-ready (no daemon required)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "Dockerfile",
    "deploy/docker/app.Dockerfile",
    "deploy/docker/ocr.Dockerfile",
    "deploy/docker/routing.Dockerfile",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    ".env.production.example",
    ".dockerignore",
    "scripts/docker_build_prod.sh",
    "scripts/docker_local_up.sh",
    "scripts/apply_mysql_migrations.py",
    "docs/DOCKER_PRODUCTION.md",
    "docs/DOCKER_LOCAL.md",
    "docs/gt/hackathon_agent_field_truth.json",
]

COPY_MUST_INCLUDE = (
    "deploy/mysql",
    "docs/gt",
    "packages",
    "apps",
    "workers",
    "config",
    "scripts",
)


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            errors.append(f"missing {rel}")

    migrations = list((ROOT / "deploy/mysql/migrations").glob("*.sql"))
    if not migrations:
        errors.append("no SQL migrations under deploy/mysql/migrations")

    for df in (
        "Dockerfile",
        "deploy/docker/app.Dockerfile",
        "deploy/docker/ocr.Dockerfile",
        "deploy/docker/routing.Dockerfile",
    ):
        text = (ROOT / df).read_text(encoding="utf-8")
        for needle in COPY_MUST_INCLUDE:
            if needle not in text:
                errors.append(f"{df}: missing COPY path mention `{needle}`")
        if "USER appuser" not in text and "USER " not in text:
            errors.append(f"{df}: no non-root USER")

    prod = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    if "CDP_ENV: production" not in prod and "CDP_ENV=production" not in prod:
        errors.append("docker-compose.prod.yml does not pin CDP_ENV=production")
    if ".env.production" not in prod:
        errors.append("docker-compose.prod.yml missing .env.production")

    example = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    for key in (
        "CDP_ENV=production",
        "DATABASE_URL=",
        "OBJECT_STORE_ACCESS_KEY=",
        "USE_IN_MEMORY_BUS=false",
    ):
        if key not in example:
            errors.append(f".env.production.example missing {key}")

    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    if "evaluation_results" not in ignore:
        errors.append(".dockerignore should exclude evaluation_results")
    if re.search(r"(?m)^docs/gt", ignore):
        errors.append(".dockerignore must not exclude docs/gt")

    if errors:
        print("DOCKER_DEPLOY_READY=FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("DOCKER_DEPLOY_READY=PASS")
    print(f"  migrations={len(migrations)}")
    print(f"  dockerfiles=app,ocr,routing,+root")
    print(f"  compose=docker-compose.yml + docker-compose.prod.yml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
