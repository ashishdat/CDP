"""Privacy-minimized authorized reference adapter and multi-attribute decision."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from packages.reference_providers import (
    MemberReference,
    ProviderReference,
    member_reference_passes,
)


@dataclass(frozen=True)
class ReferenceDecision:
    decision: str
    provider: str
    dataset_version: str
    matching_attributes: tuple[str, ...]
    name_similarity: float
    contradictions: tuple[str, ...]
    policy_version: str = "reference-match-v1"


class AuthorizedJsonMemberProvider:
    """Pilot adapter; records are injected by an authorized operator."""

    def __init__(self, path: Path, *, provider_name: str, dataset_version: str) -> None:
        self.path = path
        self.provider_name = provider_name
        self.dataset_version = dataset_version

    def lookup_member(self, member_id: str) -> list[MemberReference]:
        if not self.path.is_file():
            return []
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            MemberReference(**row) for row in rows
            if row["member_id"] == member_id
        ]

    def decide(
        self, *, member_id: str | None, dob: str | None, name_similarity: float,
        address_contradiction: bool,
    ) -> ReferenceDecision:
        if not member_id or not dob:
            return self._decision("HUMAN_REVIEW_REQUIRED", (), name_similarity, ("MISSING_ID_OR_DOB",))
        matches = self.lookup_member(member_id)
        if len(matches) != 1:
            return self._decision("HUMAN_REVIEW_REQUIRED", ("member_id",), name_similarity, ("REFERENCE_NOT_UNIQUE",))
        record = matches[0]
        contradictions = ("ADDRESS_CONTRADICTION",) if address_contradiction else ()
        passed = member_reference_passes(
            record, member_id=member_id, dob=dob, name_similarity=name_similarity,
            contradictory_evidence=address_contradiction,
        )
        attributes = ("member_id", "dob", "name") if record.dob == dob else ("member_id",)
        return self._decision(
            "REFERENCE_VERIFIED" if passed else "HUMAN_REVIEW_REQUIRED",
            attributes, name_similarity, contradictions,
        )

    def _decision(self, decision, attributes, similarity, contradictions):
        return ReferenceDecision(
            decision, self.provider_name, self.dataset_version,
            tuple(attributes), similarity, tuple(contradictions),
        )


class AuthorizedJsonProviderDirectory:
    """Privacy-minimized provider-master adapter keyed by exact NPI."""

    def __init__(self, path: Path, *, provider_name: str, dataset_version: str) -> None:
        self.path = path
        self.provider_name = provider_name
        self.dataset_version = dataset_version

    def lookup_npi(self, npi: str) -> ProviderReference | None:
        if not self.path.is_file() or not npi:
            return None
        matches = [
            ProviderReference(**row)
            for row in json.loads(self.path.read_text(encoding="utf-8"))
            if row["npi"] == npi
        ]
        return matches[0] if len(matches) == 1 else None

    def decide(
        self, *, npi: str | None, name_similarity: float,
        address_contradiction: bool,
        minimum_name_similarity: float = 0.92,
    ) -> ReferenceDecision:
        record = self.lookup_npi(npi or "")
        contradictions = (
            ("ADDRESS_CONTRADICTION",) if address_contradiction else ()
        )
        passed = (
            record is not None
            and record.npi == npi
            and name_similarity >= minimum_name_similarity
            and not address_contradiction
        )
        attributes = ("npi", "name") if passed else (("npi",) if record else ())
        return ReferenceDecision(
            decision="REFERENCE_VERIFIED" if passed else "HUMAN_REVIEW_REQUIRED",
            provider=self.provider_name,
            dataset_version=self.dataset_version,
            matching_attributes=tuple(attributes),
            name_similarity=name_similarity,
            contradictions=contradictions or (
                () if record else ("REFERENCE_NOT_UNIQUE_OR_MISSING",)
            ),
            policy_version="provider-reference-match-v1",
        )
