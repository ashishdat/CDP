"""50-sample Golden Pack V2 accuracy + HITL measurement.

Stratified slice: 25 CMS1500 + 25 UB04 from CDP_GOLDEN_ENGINEERING_PACK_V2.
Uses the live standard-form extraction path and scores Exact field accuracy
plus field/claim HITL from validation_status.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.extraction_geometry import FormIdentityDecision, FormIdentityStatus
from packages.local_evidence_cascade import decide_local_candidate
from packages.page_observation import PageObservationService
from packages.templates import TemplateRegistry
from workers.page_detection.text_extraction import (
    RapidOCRFullPageTextExtractor,
    RapidOCRTextExtractor,
)
from workers.standard_form_extraction import (
    StandardFormExtractionService,
    StandardFormProcessingService,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_data/phase8_6_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V2"
OUTPUT = ROOT / "evaluation_results/accuracy_50_sample"
AUTO_ACCEPTED = {"AUTO_ACCEPTED", "ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}


def _canonical(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", _canonical(value))


def _exact(predicted: object, expected: object, datatype: str) -> bool:
    if _canonical(predicted) == _canonical(expected):
        return True
    left = decide_local_candidate(str(predicted or ""), datatype)
    right = decide_local_candidate(str(expected or ""), datatype)
    if left.normalized_value and right.normalized_value:
        if _canonical(left.normalized_value) == _canonical(right.normalized_value):
            return True
    return bool(_compact(predicted) and _compact(predicted) == _compact(expected))


def _status_name(value: object) -> str:
    if value is None:
        return "MISSING"
    return str(getattr(value, "name", None) or getattr(value, "value", None) or value)


def _is_hitl(status: str) -> bool:
    return status.upper() not in AUTO_ACCEPTED


def _select_docs(manifest: dict, *, cms: int = 25, ub: int = 25) -> list[dict]:
    cms_docs = [doc for doc in manifest["documents"] if str(doc["document_id"]).startswith("CMS")]
    ub_docs = [doc for doc in manifest["documents"] if str(doc["document_id"]).startswith("UB")]
    return cms_docs[:cms] + ub_docs[:ub]


def run(*, cms: int = 25, ub: int = 25) -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((DATASET / "manifest.json").read_text("utf-8"))
    truth_rows = list(csv.DictReader((DATASET / "field_truth.csv").open(encoding="utf-8")))
    truth_by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in truth_rows:
        truth_by_doc[row["document_id"]].append(row)

    docs = _select_docs(manifest, cms=cms, ub=ub)
    templates = TemplateRegistry.load_from_directory()
    observation_service = PageObservationService(
        RapidOCRFullPageTextExtractor(),
        preprocessing_version="document-preparation-v1",
    )
    extractor = StandardFormExtractionService(RapidOCRTextExtractor())
    processor = StandardFormProcessingService(observation_service, extractor)

    field_records: list[dict] = []
    claim_records: list[dict] = []
    started_all = time.perf_counter()

    for index, doc in enumerate(docs, 1):
        doc_id = doc["document_id"]
        family = "CMS1500" if doc_id.startswith("CMS") else "UB04"
        image = Image.open(DATASET / doc["file"]).convert("RGB")
        identity = FormIdentityDecision(
            family=DocumentClass.CMS1500 if family == "CMS1500" else DocumentClass.UB04,
            status=FormIdentityStatus.VERIFIED,
            score=1.0,
        )
        template = (
            templates.get("cms1500", "02-12")
            if family == "CMS1500"
            else templates.get("ub04", "2014")
        )
        started = time.perf_counter()
        observation = observation_service.observe(
            doc_id, image, page_sha256=doc["sha256"]
        )
        processing = processor.process(
            image,
            template,
            1,
            identity,
            page_id=doc_id,
            page_sha256=doc["sha256"],
            observation=observation,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        extracted = {field.field_name: field for field in processing.fields}
        definitions = processing.field_definitions or {}
        doc_exact: list[bool] = []
        doc_hitl: list[bool] = []
        for truth in truth_by_doc[doc_id]:
            name = truth["field_name"]
            expected = truth["expected_value"]
            predicted = extracted.get(name)
            definition = definitions.get(name)
            datatype = getattr(definition, "datatype", "TEXT") if definition else "TEXT"
            value = None
            status = "MISSING"
            if predicted is not None:
                value = predicted.normalized_value
                if value in (None, ""):
                    value = predicted.raw_value
                status = _status_name(predicted.validation_status)
            exact = _exact(value, expected, datatype)
            hitl = _is_hitl(status)
            doc_exact.append(exact)
            doc_hitl.append(hitl)
            field_records.append(
                {
                    "document_id": doc_id,
                    "family": family,
                    "variant": doc.get("variant"),
                    "field_name": name,
                    "expected": expected,
                    "predicted": value,
                    "datatype": datatype,
                    "exact": exact,
                    "validation_status": status,
                    "hitl": hitl,
                }
            )
        claim_hitl = any(doc_hitl)
        claim_records.append(
            {
                "document_id": doc_id,
                "family": family,
                "variant": doc.get("variant"),
                "field_count": len(doc_exact),
                "exact_fields": sum(doc_exact),
                "exact_rate": sum(doc_exact) / max(1, len(doc_exact)),
                "hitl_fields": sum(doc_hitl),
                "claim_hitl": claim_hitl,
                "claim_stp": not claim_hitl,
                "claim_perfect_exact": all(doc_exact) if doc_exact else False,
                "latency_ms": elapsed_ms,
            }
        )
        print(
            f"[{index}/{len(docs)}] {doc_id} exact={sum(doc_exact)}/{len(doc_exact)} "
            f"hitl_fields={sum(doc_hitl)} claim_hitl={claim_hitl} {elapsed_ms:.0f}ms",
            flush=True,
        )

    by_family = {}
    for family_name in ("CMS1500", "UB04"):
        scoped = [row for row in field_records if row["family"] == family_name]
        claims = [row for row in claim_records if row["family"] == family_name]
        by_family[family_name] = {
            "documents": len(claims),
            "fields": len(scoped),
            "exact_accuracy": sum(row["exact"] for row in scoped) / max(1, len(scoped)),
            "field_hitl": sum(row["hitl"] for row in scoped) / max(1, len(scoped)),
            "claim_hitl": sum(row["claim_hitl"] for row in claims) / max(1, len(claims)),
            "claim_stp": sum(row["claim_stp"] for row in claims) / max(1, len(claims)),
            "perfect_claim_exact": sum(row["claim_perfect_exact"] for row in claims)
            / max(1, len(claims)),
        }

    critical_names = {
        "provider_npi",
        "total_charge",
        "patient_name",
        "patient_dob",
        "diagnosis",
        "principal_diagnosis",
        "cpt_hcpcs",
        "member_id",
        "insured_name",
    }
    critical = [row for row in field_records if row["field_name"] in critical_names]
    status_counts = Counter(row["validation_status"] for row in field_records)
    failure_fields = Counter(row["field_name"] for row in field_records if not row["exact"])
    latencies = sorted(row["latency_ms"] for row in claim_records)

    report = {
        "dataset_id": manifest.get("dataset_id"),
        "sample_size": len(docs),
        "cms_docs": cms,
        "ub_docs": ub,
        "field_count": len(field_records),
        "exact_accuracy": sum(row["exact"] for row in field_records)
        / max(1, len(field_records)),
        "critical_exact_accuracy": sum(row["exact"] for row in critical)
        / max(1, len(critical)),
        "field_hitl": sum(row["hitl"] for row in field_records) / max(1, len(field_records)),
        "claim_hitl": sum(row["claim_hitl"] for row in claim_records)
        / max(1, len(claim_records)),
        "claim_stp": sum(row["claim_stp"] for row in claim_records)
        / max(1, len(claim_records)),
        "perfect_claim_exact": sum(row["claim_perfect_exact"] for row in claim_records)
        / max(1, len(claim_records)),
        "false_accepts": sum(
            1
            for row in field_records
            if (not row["exact"]) and (not row["hitl"]) and row["predicted"] not in (None, "")
        ),
        "validation_status_counts": dict(status_counts),
        "by_family": by_family,
        "top_exact_failures": failure_fields.most_common(15),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else 0.0,
            "mean": sum(latencies) / max(1, len(latencies)),
            "max": max(latencies) if latencies else 0.0,
        },
        "elapsed_s": time.perf_counter() - started_all,
        "note": (
            "HITL uses live validation_status: anything other than AUTO_ACCEPTED/"
            "REFERENCE_CONFIRMED/HUMAN_CONFIRMED counts as field HITL. Claim STP "
            "requires zero HITL fields on the claim."
        ),
    }

    (OUTPUT / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "field_records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in field_records), encoding="utf-8"
    )
    (OUTPUT / "claim_records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in claim_records), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    result = run(cms=25, ub=25)
    printable = {key: value for key, value in result.items() if key != "note"}
    print(json.dumps(printable, indent=2))
    print(result["note"])
