"""Run profiles — FAST (latency) vs PRODUCT (STP gate) vs TIP_SEED."""

from packages.run_profiles.profiles import (
    ProfileError,
    RunProfile,
    apply_profile_env,
    detect_live_profile,
    gate_allows_profile,
    load_profiles,
    write_run_manifest,
)

__all__ = [
    "ProfileError",
    "RunProfile",
    "apply_profile_env",
    "detect_live_profile",
    "gate_allows_profile",
    "load_profiles",
    "write_run_manifest",
]
