"""Read-only connector for independently finalized downstream claim values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Protocol

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DownstreamFieldValue:
    claim_identifier: str
    document_identifier: str | None
    field_name: str
    value: str
    finalized_at: str
    source_system: str
    source_record_version: str
    lineage_origin: str
    derived_from_cdp: bool
    audit_reference: str


class FinalizedClaimsConnector(Protocol):
    def readiness(self) -> dict: ...
    def finalized_fields(self, claim_identifier: str) -> list[DownstreamFieldValue]: ...


class SqlAlchemyFinalizedClaimsConnector:
    """Parameterized, allow-listed SQL adapter; never writes to the source DB."""

    REQUIRED_COLUMNS: ClassVar[set[str]] = {
        "claim_identifier", "document_identifier", "field_name", "field_value",
        "finalized_at", "source_record_version", "lineage_origin", "derived_from_cdp",
        "audit_reference",
    }

    def __init__(self, engine: Engine, *, table: str, source_system: str) -> None:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError("unsafe downstream table identifier")
        self.engine = engine
        self.table = table
        self.source_system = source_system

    def readiness(self) -> dict:
        try:
            with self.engine.connect() as connection:
                columns = connection.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :table AND table_schema = current_schema()"
                ), {"table": self.table}).scalars().all()
            missing = sorted(self.REQUIRED_COLUMNS - set(columns))
            return {
                "connector": "FINALIZED_DOWNSTREAM_CLAIMS",
                "status": "READY" if not missing else "SCHEMA_INCOMPLETE",
                "read_only": True,
                "database_dialect": self.engine.dialect.name,
                "missing_columns": missing,
            }
        except SQLAlchemyError as error:  # readiness reports connectivity failures
            return {
                "connector": "FINALIZED_DOWNSTREAM_CLAIMS", "status": "UNAVAILABLE",
                "read_only": True, "error_type": type(error).__name__,
            }

    def finalized_fields(self, claim_identifier: str) -> list[DownstreamFieldValue]:
        statement = text(
            f"SELECT claim_identifier, document_identifier, field_name, field_value, "
            "finalized_at, source_record_version, lineage_origin, derived_from_cdp, "
            f"audit_reference FROM {self.table} "
            "WHERE claim_identifier = :claim_id AND finalized_at IS NOT NULL"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {"claim_id": claim_identifier}).mappings()
            return [
                DownstreamFieldValue(
                    claim_identifier=str(row["claim_identifier"]),
                    document_identifier=str(row["document_identifier"]) if row["document_identifier"] else None,
                    field_name=str(row["field_name"]), value=str(row["field_value"]),
                    finalized_at=str(row["finalized_at"]), source_system=self.source_system,
                    source_record_version=str(row["source_record_version"]),
                    lineage_origin=str(row["lineage_origin"]),
                    derived_from_cdp=bool(row["derived_from_cdp"]),
                    audit_reference=str(row["audit_reference"]),
                )
                for row in rows
            ]
