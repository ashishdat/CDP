"""Source inventory with no secret or reference-record disclosure."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Protocol

from sqlalchemy import create_engine

from packages.downstream_claims_connector import SqlAlchemyFinalizedClaimsConnector


class ReadinessProvider(Protocol):
    def readiness(self) -> dict: ...


def scan_sources(sources: dict[str, ReadinessProvider | None]) -> dict:
    checks = {}
    for name, source in sources.items():
        checks[name] = {"status": "NOT_CONFIGURED"} if source is None else source.readiness()
    ready = [name for name, result in checks.items() if result.get("status") == "READY"]
    return {
        "source_readiness": checks,
        "operational_connectors": len(ready),
        "first_milestone_met": bool(ready),
        "ready_sources": ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/trusted_sources/readiness.json"))
    parser.add_argument("--downstream-url-env", default="DOWNSTREAM_CLAIMS_DATABASE_URL")
    parser.add_argument("--downstream-table", default=os.getenv(
        "DOWNSTREAM_CLAIMS_TABLE", "trusted_finalized_claim_fields"
    ))
    parser.add_argument("--downstream-source-system", default=os.getenv(
        "DOWNSTREAM_CLAIMS_SOURCE_SYSTEM", "authorized-downstream-claims"
    ))
    args = parser.parse_args()
    database_url = os.getenv(args.downstream_url_env)
    downstream = None
    if database_url:
        downstream = SqlAlchemyFinalizedClaimsConnector(
            create_engine(database_url), table=args.downstream_table,
            source_system=args.downstream_source_system,
        )
    report = scan_sources({
        "finalized_downstream_claims": downstream,
        "authorized_member_source": None,
        "authorized_provider_registry": None,
        "approved_correction_audit": None,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["first_milestone_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
