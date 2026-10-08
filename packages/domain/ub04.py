"""Institutional claim service-line observations, distinct from CMS Box 24."""
from typing import Literal
from pydantic import Field, TypeAdapter, field_validator
from packages.domain.common import DomainModel
from packages.ocr.contracts import OCRCandidate

class UB04CellObservation(DomainModel):
    canonical_region: tuple[int,int,int,int]
    candidates: list[dict] = Field(default_factory=list)
    attempts: list[dict] = Field(default_factory=list)
    router_reason: str | None = None

    @field_validator("candidates")
    @classmethod
    def validate_observations(cls, candidates):
        for candidate in candidates:
            TypeAdapter(OCRCandidate).validate_python(candidate)
        return candidates


class UB04ServiceCells(DomainModel):
    revenue_code: UB04CellObservation
    description: UB04CellObservation
    hcpcs_rate: UB04CellObservation
    service_date: UB04CellObservation
    service_units: UB04CellObservation
    total_charges: UB04CellObservation
    non_covered_charges: UB04CellObservation

class UB04ServiceLine(DomainModel):
    schema_version: Literal["ub04-service-lines-v1"] = "ub04-service-lines-v1"
    row_number: int = Field(ge=1,le=22)
    canonical_region: tuple[int,int,int,int]
    cells: UB04ServiceCells
    status: Literal["CANDIDATES_OBSERVED"] = "CANDIDATES_OBSERVED"
    financial_authority: Literal[False] = False
