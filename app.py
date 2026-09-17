"""One-document application assembly; stop and preserve state at the first failure."""

import argparse
import json
import logging
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image

from datasets.registry import DatasetManager

LOGGER = logging.getLogger("cdp.application")
STAGES = ("load", "classification", "template_selection", "registration", "geometry", "ocr", "ranking",
          "validators", "decision", "evidence")


def register_classified_document(images, routing, registry, selection=None):
    """Bind the selected page to existing image registration, without field geometry.

    Registration acceptance does not authorize extraction or establish form identity.
    No page-corner correspondences or substitute template are manufactured.
    """
    from workers.page_detection.registration_telemetry import registration_context
    from workers.page_detection.template_alignment import align_to_reference

    if selection is not None:
        if selection.template_id is None:
            return {"status": "UNAVAILABLE", "accepted": False, "reason": selection.reason,
                    "page_number": None, "evidence": None, "transform_matrix": None}
        from types import SimpleNamespace

        routing = SimpleNamespace(
            needs_review=False, selected_page_number=selection.page_number,
            template=registry.get(selection.template_id, selection.template_version),
        )
    result = {"status": "UNAVAILABLE", "accepted": False, "reason": None,
              "page_number": routing.selected_page_number, "evidence": None,
              "transform_matrix": None}
    if routing.needs_review or routing.template is None or routing.selected_page_number is None:
        result["reason"] = "CLASSIFICATION_HAS_NO_UNAMBIGUOUS_TEMPLATE_PAGE"
        return result
    page_number = routing.selected_page_number
    if not 1 <= page_number <= len(images):
        result.update(status="FAILED", reason="SELECTED_PAGE_OUT_OF_RANGE")
        return result
    template = routing.template
    result.update(template_id=template.template_id, template_version=template.version)
    reference = registry.load_reference_image(template)
    if reference is None:
        result["reason"] = "REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE"
        return result
    aligned = None
    try:
        size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
        if reference.size != size:
            resized = reference.resize(size)
            reference.close()
            reference = resized
        with registration_context(template_id=template.template_id, page_number=page_number):
            aligned = align_to_reference(
                images[page_number - 1], reference, family=template.form_type.value,
                enforce_compatibility_precheck=True,
            )
        evidence = aligned.evidence
        accepted = (aligned.success and aligned.accepted and aligned.warped is not None
                    and evidence is not None and evidence.accepted
                    and evidence.corner_validity is True)
        result.update(
            status="SUCCESS" if accepted else "FAILED", accepted=accepted,
            reason="REGISTRATION_ACCEPTED" if accepted else (
                evidence.rejection_reason if evidence and evidence.rejection_reason
                else "REGISTRATION_NOT_ACCEPTED"),
            evidence=evidence.model_dump(mode="json") if evidence else None,
            compatibility=(aligned.compatibility.model_dump(mode="json")
                           if aligned.compatibility else None),
            transform_matrix=aligned.homography.tolist() if accepted else None,
            method=aligned.method,
        )
        return result
    finally:
        reference.close()
        if aligned is not None and aligned.warped is not None:
            aligned.warped.close()



def resolve_registered_geometry(images, registration, registry):
    """Consume only an accepted transform; resolve fields on the rectified page."""
    import cv2
    import numpy as np
    from packages.geometry.engine import GeometryEngine, GeometryRequest
    from packages.geometry.models import Box, Registration

    if registration.get('accepted') is not True or registration.get('status') != 'SUCCESS':
        raise ValueError('Geometry requires successful registration')
    evidence = registration.get('evidence') or {}
    if evidence.get('accepted') is not True or evidence.get('corner_validity') is not True:
        raise ValueError('Geometry requires accepted registration evidence')
    matrix = np.asarray(registration.get('transform_matrix'), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError('Accepted registration transform is missing or invalid')
    template = registry.get(registration['template_id'], registration['template_version'])
    page_number = registration['page_number']
    if not 1 <= page_number <= len(images):
        raise ValueError('Registered page is out of range')
    size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    with images[page_number - 1].convert('L') as source:
        rectified = cv2.warpPerspective(np.asarray(source), matrix, size, borderValue=255)
    # The accepted projective transform has already mapped pixels into template space.
    # Identity here is a coordinate mapping, never an estimated registration or landmark.
    mapping = Registration(True, ((1., 0., 0.), (0., 1., 0.)), None,
                           'ACCEPTED_REGISTRATION_RECTIFIED_FRAME')
    fields = []
    for field in template.field_regions:
        started = perf_counter()
        box = Box(field.x0, field.y0, field.x1, field.y1)
        result = GeometryEngine().resolve(GeometryRequest(
            rectified, (), (), box, box, accepted_mapping=mapping))
        fields.append({'field': field.field_name, 'result': asdict(result),
                       'latency_ms': (perf_counter() - started) * 1000})
        if result.reasons not in [('GEOMETRY_RESOLVED',), ('NO_FOREGROUND',)]:
            return {'type': 'GeometryResult', 'status': 'FAILED', 'fields': fields,
                    'reason': result.reasons, 'coordinate_frame': 'rectified_template_pixels'}
    return {'type': 'GeometryResult', 'status': 'SUCCESS' if fields else 'FAILED',
            'reason': 'GEOMETRY_RESOLVED' if fields else 'NO_TEMPLATE_FIELDS',
            'page_number': page_number, 'coordinate_frame': 'rectified_template_pixels',
            'source_to_geometry_transform': matrix.tolist(), 'fields': fields,
            'warnings': ['NO_FOREGROUND is an empty geometry result, not an OCR or validation decision']}

def process_one(dataset_path="dataset.yaml", *, document=None, output_root="runs",
                document_type=None, classification_only=False):
    """Decode one entire TIFF in memory, then invoke existing runtime routing.

    This assembly stops at the first missing integration. It does not replace
    production routing, fabricate registration, or report unexecuted stages as
    successful. Later stages remain skipped until their bindings are assembled.
    """
    output = Path(output_root) / ("application-" + uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    state = {
        "document_id": None, "page_count": 0, "fields": [],
        "status": "FAILED", "stages": {name: "SKIPPED" for name in STAGES},
        "geometry": None, "ocr": None, "ranking": None, "validators": None,
        "decision": None, "evidence": None,
        "latency_ms": {name: None for name in STAGES}, "errors": [], "warnings": [],
    }
    images = []
    stage = "load"
    from workers.page_detection.registration_telemetry import collect_traces, save_traces

    collection = collect_traces()
    traces = collection.__enter__()
    total_started = started = perf_counter()
    try:
        dataset = DatasetManager.load(dataset_path)
        state["dataset"] = dataset.describe()
        verification = dataset.verify()
        state["dataset_verification"] = verification
        if not verification["verified"]:
            raise ValueError("Registered archive integrity verification failed")
        with ZipFile(dataset.root, "r") as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if document is not None:
                entries = [entry for entry in entries if entry.filename == document]
            if not entries or (document is not None and len(entries) != 1):
                raise ValueError("Document selection must identify exactly one ZIP entry")
            entry = entries[0]
            payload = archive.read(entry)
        state["source"] = {"archive": str(dataset.root), "entry": entry.filename}
        state["document_id"] = sha256(payload).hexdigest()
        with Image.open(BytesIO(payload)) as image:
            if image.format != "TIFF":
                raise ValueError("Selected document is not TIFF")
            state["page_count"] = image.n_frames
            for frame in range(image.n_frames):
                image.seek(frame)
                images.append(image.convert("RGB"))
        state["pages"] = [{"page_number": index, "width": image.width,
                           "height": image.height} for index, image in enumerate(images, 1)]
        state["stages"][stage] = "SUCCESS"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        LOGGER.info("load SUCCESS: %s, %s pages", entry.filename, len(images))

        stage = "classification"
        started = perf_counter()
        from packages.domain.enums import ClaimFormType
        from packages.templates.registry import TemplateRegistry
        from workers.cascade.tesseract_adapter import TesseractTextExtractor
        from workers.page_detection.router import PageRoutingService
        from workers.page_detection.template_selector import TemplateSelector

        observed_lines = {}

        class ClassificationTextExtractor(TesseractTextExtractor):
            def extract(self, image):
                lines = super().extract(image)
                observed_lines[id(image)] = lines
                return lines

        from workers.page_detection.page_classification import classify_page, write_classification_report
        registry = TemplateRegistry.load_from_directory()
        classifier = ClassificationTextExtractor(psm=11)
        templates = [t for family in ClaimFormType for t in registry.all_for_form_type(family)]
        page_classifications = [classify_page(image, classifier.extract(image), templates, page)
                                for page, image in enumerate(images, 1)]
        state["page_classifications"] = [asdict(item) for item in page_classifications]
        write_classification_report(page_classifications, output)
        if classification_only:
            state["stages"][stage] = "SUCCESS"
            state["latency_ms"][stage] = (perf_counter() - started) * 1000
            state["status"] = "SUCCESS"
            state["stop_after"] = "classification"
            return output / "document.json", state

        class CachedClassificationTextExtractor:
            def extract(self, image):
                return observed_lines[id(image)]

        cms = registry.latest_for_form_type(ClaimFormType.CMS1500)
        ub = registry.latest_for_form_type(ClaimFormType.UB04)
        router = PageRoutingService(
            cms_template=cms, ub_template=ub, text_extractor=CachedClassificationTextExtractor(),
            cms_reference_image=registry.load_reference_image(cms),
            ub_reference_image=registry.load_reference_image(ub),
        )
        routing = router.route(images)
        state["classification"] = asdict(routing)
        state["stages"][stage] = "SUCCESS"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        LOGGER.info("classification SUCCESS")
        stage = "template_selection"
        started = perf_counter()
        selection = TemplateSelector(registry).select(
            images, text_lines={page: observed_lines.get(id(image), [])
                                for page, image in enumerate(images, 1)},
            document_type=document_type,
        )
        state["template_selection"] = asdict(selection)
        state["stages"][stage] = "SUCCESS" if selection.template_id else "UNAVAILABLE"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        LOGGER.info("template_selection %s: %s", state["stages"][stage], selection.reason)
        stage = "registration"
        started = perf_counter()
        state["registration"] = register_classified_document(images, routing, registry, selection)
        result = state["registration"]
        state["stages"][stage] = result["status"]
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        state["geometry"] = {"status": "SKIPPED", "reason": "STOP_AFTER_REGISTRATION"}
        state["stop_after"] = "registration"
        state["status"] = "SUCCESS" if result["accepted"] else "FAILED"
        if not result["accepted"]:
            state["errors"].append({"stage": stage, "type": "RegistrationNotAccepted",
                                    "message": result["reason"]})
        LOGGER.info("registration %s: %s", result["status"], result["reason"])
        if result['accepted']:
            stage = 'geometry'
            started = perf_counter()
            state['geometry'] = resolve_registered_geometry(images, result, registry)
            state['latency_ms'][stage] = (perf_counter() - started) * 1000
            state['stages'][stage] = state['geometry']['status']
            state['status'] = state['geometry']['status']
            state['stop_after'] = 'geometry'
            (output / 'GeometryResult.json').write_text(
                json.dumps(state['geometry'], indent=2, allow_nan=False), encoding='utf-8')
            (output / 'geometry_telemetry.json').write_text(json.dumps({
                'stage': stage, 'status': state['status'], 'latency_ms': state['latency_ms'][stage],
                'registration_reference': 'registration_trace.json',
                'result_reference': 'GeometryResult.json', 'ocr_executed': False,
                'registration_evidence': result['evidence'],
                'source': state['source'], 'document_id': state['document_id'],
            }, indent=2), encoding='utf-8')

    except Exception as exc:  # noqa: BLE001 -- persist state before exiting nonzero
        unavailable = isinstance(exc, (ImportError, FileNotFoundError, NotImplementedError))
        state["stages"][stage] = "UNAVAILABLE" if unavailable else "FAILED"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        state["errors"].append({"stage": stage, "type": type(exc).__name__, "message": str(exc)})
        LOGGER.error("%s %s: %s", stage, state["stages"][stage], exc)
    finally:
        for image in images:
            image.close()
        state["latency_ms"]["total"] = (perf_counter() - total_started) * 1000
        collection.__exit__(None, None, None)
        state["registration_trace"] = {"type": "RegistrationTrace", "traces": [trace.snapshot() for trace in traces]}
        try:
            save_traces(traces, output)
        except OSError:
            LOGGER.exception("Registration trace could not be written")
        (output / "document.json").write_text(
            json.dumps(state, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8",
        )
        try:
            from workers.page_detection.template_discovery import write_report

            write_report(state, output)
        except Exception:
            LOGGER.exception("Template discovery report could not be written")
        try:
            from workers.page_detection.registration_diagnostics import (
                write_report as write_registration_report,
            )

            write_registration_report(state, output)
        except Exception:
            LOGGER.exception("Registration report could not be written")
    return output / "document.json", state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="dataset.yaml")
    parser.add_argument("--document", help="Exact ZIP entry; default is first document")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--document-type", choices=("CMS1500", "UB04", "UNSTRUCTURED"),
                        help="Explicit operator-supplied document type; never inferred from filename")
    parser.add_argument("--classification-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path, state = process_one(args.dataset, document=args.document, output_root=args.output_root,
                              document_type=args.document_type, classification_only=args.classification_only)
    print(path.resolve())
    return 0 if state["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
