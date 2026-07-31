"""Authoritative member/provider reference matching for OCR verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol


@dataclass(frozen=True)
class ReferenceRecord:
    record_id: str
    member_id: str | None = None
    patient_name: str | None = None
    patient_dob: str | None = None
    address: str | None = None
    provider_npi: str | None = None


@dataclass(frozen=True)
class ReferenceMatch:
    record_id: str
    score: float
    exact_fields: tuple[str, ...]
    fuzzy_fields: tuple[str, ...]
    verified: bool


class ReferenceDataProvider(Protocol):
    def candidates(
        self, member_id: str | None, provider_npi: str | None
    ) -> list[ReferenceRecord]: ...


class ReferenceMatcher:
    def __init__(self, provider: ReferenceDataProvider, minimum_score: float = 0.92) -> None:
        self._provider = provider
        self._minimum_score = minimum_score

    def verify(
        self,
        values: dict[str, str | None],
    ) -> ReferenceMatch | None:
        records = self._provider.candidates(
            values.get("member_id"), values.get("provider_npi")
        )
        matches = [self._score(record, values) for record in records]
        best = max(matches, key=lambda item: item.score, default=None)
        if best is None:
            return None
        return ReferenceMatch(
            best.record_id,
            best.score,
            best.exact_fields,
            best.fuzzy_fields,
            best.score >= self._minimum_score and bool(best.exact_fields),
        )

    def _score(self, record: ReferenceRecord, values: dict[str, str | None]) -> ReferenceMatch:
        pairs = {
            "member_id": (record.member_id, values.get("member_id")),
            "patient_name": (record.patient_name, values.get("patient_name")),
            "patient_dob": (record.patient_dob, values.get("patient_dob")),
            "address": (record.address, values.get("address")),
            "provider_npi": (record.provider_npi, values.get("provider_npi")),
        }
        weights = {
            "member_id": 0.30, "patient_name": 0.25, "patient_dob": 0.20,
            "address": 0.10, "provider_npi": 0.15,
        }
        exact: list[str] = []
        fuzzy: list[str] = []
        score = available = 0.0
        for name, (expected, actual) in pairs.items():
            if not expected or not actual:
                continue
            available += weights[name]
            left, right = _normalize(expected), _normalize(actual)
            similarity = 1.0 if left == right else SequenceMatcher(None, left, right).ratio()
            score += weights[name] * similarity
            (exact if similarity == 1 else fuzzy).append(name)
        normalized_score = score / available if available else 0.0
        return ReferenceMatch(
            record.record_id, normalized_score, tuple(exact), tuple(fuzzy), False
        )


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())
