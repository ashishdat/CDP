"""All-page candidate generation, completeness enforcement and field routing."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from packages.domain.common import BoundingBox
from packages.domain.document import Document
from packages.ocr.contracts import OCRCandidate
from workers.field_candidates.contracts import (
    CandidateStatus,
    FieldCandidateProvider,
    FieldInferenceCompleteness,
    FieldSpec,
    PageFieldCandidate,
    PreparedPage,
)
from workers.unstructured_extraction.evidence_selector import (
    FieldEvidenceDecision,
    FieldEvidenceSelector,
    PageFieldEvidence,
)


@dataclass(frozen=True)
class FieldRoutingOutcome:
    field_name: str
    completeness: FieldInferenceCompleteness
    decision: FieldEvidenceDecision | None
    disposition: str


class CandidateStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def cache_path(
        self, page: PreparedPage, provider: FieldCandidateProvider, field: FieldSpec
    ) -> Path:
        digest = hashlib.sha256(
            (
                f"{page.image_sha256}|{provider.provider_name}|"
                f"{provider.provider_version}|{provider.model_name}|"
                f"{provider.model_version}|{field.field_name}"
            ).encode()
        ).hexdigest()
        return self.root / "cache" / f"{digest}.json"

    def load(self, path: Path) -> PageFieldCandidate | None:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = CandidateStatus(payload["status"])
        payload["hard_validation_results"] = tuple(payload["hard_validation_results"])
        payload["bounding_box"] = (
            tuple(payload["bounding_box"]) if payload["bounding_box"] else None
        )
        return PageFieldCandidate(**payload)

    def save(self, path: Path, candidate: PageFieldCandidate) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(candidate), indent=2), encoding="utf-8")

    def persist_document(
        self,
        document_id: str,
        candidates: list[PageFieldCandidate],
        completeness: list[FieldInferenceCompleteness],
    ) -> None:
        target = self.root / document_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "candidates.json").write_text(
            json.dumps([asdict(item) for item in candidates], indent=2),
            encoding="utf-8",
        )
        (target / "completeness.json").write_text(
            json.dumps([asdict(item) for item in completeness], indent=2),
            encoding="utf-8",
        )

    def persist_routing(
        self, document_id: str, outcomes: list[FieldRoutingOutcome]
    ) -> None:
        target = self.root / document_id
        payload = []
        for outcome in outcomes:
            selected = outcome.decision.selected if outcome.decision else None
            payload.append({
                "field_name": outcome.field_name,
                "disposition": outcome.disposition,
                "routing_ready": outcome.completeness.routing_ready,
                "selected_page": selected.page_number if selected else None,
                "selected_value": selected.candidate.value if selected else None,
                "selected_family": selected.document_family if selected else None,
                "score": outcome.decision.score if outcome.decision else 0.0,
                "margin": outcome.decision.margin if outcome.decision else 0.0,
                "reason": (
                    outcome.decision.reason if outcome.decision
                    else "inference_incomplete"
                ),
            })
        (target / "routing.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


class AllPageCandidatePipeline:
    def __init__(
        self,
        providers: list[FieldCandidateProvider],
        store: CandidateStore,
        selector: FieldEvidenceSelector | None = None,
    ) -> None:
        self.providers = providers
        self.store = store
        self.selector = selector or FieldEvidenceSelector()

    def run(
        self,
        document: Document,
        pages: list[PreparedPage],
        fields: list[FieldSpec],
        *,
        overwrite_incomplete: bool = False,
    ) -> tuple[list[PageFieldCandidate], list[FieldRoutingOutcome]]:
        all_candidates: list[PageFieldCandidate] = []
        outcomes: list[FieldRoutingOutcome] = []
        for field in fields:
            field_candidates: list[PageFieldCandidate] = []
            for provider in self.providers:
                for page in pages:
                    cache = self.store.cache_path(page, provider, field)
                    candidate = None if overwrite_incomplete else self.store.load(cache)
                    if candidate is None:
                        started = time.perf_counter()
                        try:
                            results = provider.extract_candidates(document, [page], field)
                            if len(results) != 1:
                                raise RuntimeError(
                                    f"{provider.provider_name} must return one terminal "
                                    "result for every attempted page"
                                )
                            candidate = results[0]
                        except Exception as exc:  # noqa: BLE001 - persisted terminal outcome
                            candidate = self._provider_error(
                                document, page, field, provider, exc, started
                            )
                        candidate = self._persist_crop(page, candidate)
                        self.store.save(cache, candidate)
                    field_candidates.append(candidate)
            completeness = self._completeness(
                field.field_name, pages, field_candidates, len(self.providers)
            )
            decision = None
            disposition = "INFERENCE_INCOMPLETE"
            if completeness.routing_ready:
                decision = self.selector.select(
                    [self._selector_evidence(item, pages) for item in field_candidates],
                    critical=field.critical,
                )
                disposition = (
                    "HUMAN_REVIEW_REQUIRED"
                    if decision.review_required
                    else "SELECTED" if decision.selected else "UNRESOLVED"
                )
            outcomes.append(
                FieldRoutingOutcome(field.field_name, completeness, decision, disposition)
            )
            all_candidates.extend(field_candidates)
        self.store.persist_document(
            str(document.document_id),
            all_candidates,
            [outcome.completeness for outcome in outcomes],
        )
        self.store.persist_routing(str(document.document_id), outcomes)
        return all_candidates, outcomes

    @staticmethod
    def _provider_error(document, page, field, provider, error, started):
        return PageFieldCandidate(
            status=CandidateStatus.PROVIDER_ERROR,
            document_id=str(document.document_id),
            field_name=field.field_name,
            page_number=page.page_number,
            document_family="unknown",
            provider_name=provider.provider_name,
            provider_version=provider.provider_version,
            raw_value=None,
            normalized_value=None,
            ocr_engine="unavailable",
            model_name="unavailable",
            model_version="unavailable",
            ocr_confidence=0.0,
            family_confidence=0.0,
            anchor_relevance=0.0,
            crop_quality=0.0,
            alignment_score=page.alignment_score,
            bounding_box=None,
            crop_reference=None,
            hard_validation_results=(),
            latency_ms=(time.perf_counter() - started) * 1000,
            failure_reason=f"{type(error).__name__}: {error}",
        )

    def _persist_crop(
        self, page: PreparedPage, candidate: PageFieldCandidate
    ) -> PageFieldCandidate:
        if not candidate.has_evidence or candidate.bounding_box is None:
            return candidate
        box = tuple(int(value) for value in candidate.bounding_box)
        crop_key = hashlib.sha256(
            f"{page.image_sha256}|{candidate.provider_name}|"
            f"{candidate.field_name}|{box}".encode()
        ).hexdigest()
        path = self.store.root / "crops" / f"{crop_key}.png"
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            page.image.crop(box).save(path, "PNG")
        return replace(candidate, crop_reference=str(path))

    @staticmethod
    def _completeness(field_name, pages, candidates, provider_count):
        attempted_pages = {item.page_number for item in candidates}
        terminal = {
            CandidateStatus.EVIDENCE,
            CandidateStatus.NO_EVIDENCE,
            CandidateStatus.PROVIDER_ERROR,
        }
        provider_pages: dict[str, set[int]] = {}
        for item in candidates:
            if item.status in terminal:
                provider_pages.setdefault(item.provider_name, set()).add(item.page_number)
        providers_completed = sum(
            len(attempted) == len(pages) for attempted in provider_pages.values()
        )
        return FieldInferenceCompleteness(
            field_name=field_name,
            page_count=len(pages),
            eligible_pages=len(pages),
            pages_attempted=len(attempted_pages),
            pages_with_candidates=len({
                item.page_number for item in candidates if item.has_evidence
            }),
            providers_expected=provider_count,
            providers_completed=providers_completed,
            routing_ready=(
                providers_completed == provider_count
                and len(attempted_pages) == len(pages)
            ),
        )

    @staticmethod
    def _selector_evidence(
        candidate: PageFieldCandidate, pages: list[PreparedPage]
    ) -> PageFieldEvidence:
        page = next(item for item in pages if item.page_number == candidate.page_number)
        box = candidate.bounding_box or (0.0, 0.0, 0.0, 0.0)
        ocr = OCRCandidate(
            value=candidate.normalized_value,
            raw_value=candidate.raw_value or "",
            engine=candidate.ocr_engine,
            model_name=candidate.model_name,
            model_version=candidate.model_version,
            preprocessing_variant="prepared",
            raw_confidence=candidate.ocr_confidence,
            calibrated_confidence=candidate.ocr_confidence,
            bounding_box=BoundingBox(
                x0=box[0], y0=box[1], x1=box[2], y1=box[3],
                image_width=page.image.width, image_height=page.image.height,
            ),
            latency_ms=candidate.latency_ms,
            validation_results=candidate.hard_validation_results,
            evidence_reference=candidate.crop_reference,
        )
        return PageFieldEvidence(
            candidate.field_name,
            candidate.page_number,
            candidate.document_family,
            ocr,
            candidate.family_confidence,
            candidate.anchor_relevance,
            candidate.crop_quality,
            candidate.has_evidence and "invalid" not in candidate.hard_validation_results,
            anchor_phrase=None,
        )
