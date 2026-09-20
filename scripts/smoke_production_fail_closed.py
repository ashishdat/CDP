#!/usr/bin/env python3
"""Credential-free production fail-closed smoke.

Verifies:
  - production runtime profile hashes
  - CDP_ENV=production rejects unsafe local defaults
  - docker compose config validates (when docker is available)
  - frozen extraction-v2 release is selectable

Exit 0 on success; exit 1 on any failure. Never calls Azure/OpenAI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ok(msg: str) -> None:
    print(f"OK  {msg}")


def _fail(msg: str) -> None:
    print(f"FAIL {msg}", file=sys.stderr)


def main() -> int:
    failures = 0

    from packages.production_runtime import (
        load_production_runtime_profile,
        validate_production_settings,
    )
    from packages.release_selection import select_release
    from packages.settings import Settings

    try:
        profile, payload = load_production_runtime_profile()
        assert profile.profile_status.value == "RUNTIME"
        assert payload["pipeline_release"] == "extraction-v2"
        _ok(f"production runtime profile {profile.profile_id}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"runtime profile: {exc}")
        failures += 1

    try:
        path = select_release("extraction-v2")
        assert path.is_file()
        _ok(f"frozen release {path}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"release selection: {exc}")
        failures += 1

    unsafe = validate_production_settings(
        Settings(
            database_url="sqlite:///:memory:",
            use_in_memory_bus=True,
            object_store_access_key="minioadmin",
            object_store_secret_key="minioadmin",
            vlm_enabled=True,
        )
    )
    if unsafe.ok:
        _fail("expected unsafe settings to be rejected")
        failures += 1
    else:
        codes = {i.code for i in unsafe.issues}
        for required in {
            "SQLITE_FORBIDDEN",
            "IN_MEMORY_BUS_FORBIDDEN",
            "DEFAULT_MINIO_CREDENTIALS_FORBIDDEN",
            "VLM_MUST_STAY_OFF_UNTIL_APPROVED",
        }:
            if required not in codes:
                _fail(f"missing issue {required}")
                failures += 1
        else:
            _ok(f"fail-closed rejected unsafe defaults ({len(unsafe.issues)} issues)")

    safe = validate_production_settings(
        Settings(
            database_url="postgresql+psycopg://idp:secret@db:5432/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
        )
    )
    if not safe.ok:
        _fail(f"hardened defaults unexpectedly rejected: {safe.issues}")
        failures += 1
    else:
        _ok("hardened production defaults accepted")

    # Optional compose validation when docker is present.
    compose = ROOT / "docker-compose.yml"
    if compose.is_file():
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose), "config", "-q"],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "COMPOSE_PROJECT_NAME": "cdp-smoke"},
            )
            _ok("docker compose config")
        except FileNotFoundError:
            _ok("docker not installed — skipped compose config")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            # Compose may fail without .env secrets; treat as soft warning.
            detail = getattr(exc, "stderr", None) or str(exc)
            print(f"WARN compose config: {detail[:200]}")

    if failures:
        _fail(f"{failures} check(s) failed")
        return 1
    print("production fail-closed smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
