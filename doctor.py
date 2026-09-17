"""Read-only registration asset check. Never runs TIFFs, OCR or registration."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import yaml
from PIL import Image

from packages.templates.canonical import CanonicalTemplateMetadata, load_canonical_image
from packages.templates.models import Template

ROOT = Path(__file__).resolve().parent


def asset(path, missing):
    if not path.is_file():
        return {"path": str(path), "sha256": None, "status": missing}
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest, "status": "READY"}


def audit_template(definition):
    row = {"definition": asset(definition, "MISSING_METADATA"), "assets": {}, "issues": []}
    try:
        template = Template.model_validate(yaml.safe_load(definition.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
        row.update(template_id=definition.stem, template_version=None, status="INVALID_METADATA",
                   issues=[str(exc)])
        return row
    package = ROOT / "templates" / template.template_id
    reference = (definition.parent / template.reference_image_path
                 if template.reference_image_path else package / "canonical.png")
    row.update(template_id=template.template_id, template_version=template.version,
               configured_reference=template.reference_image_path, dimensions=template.reference_dimensions.model_dump(),
               safe_cell_file=None, resolution={"embedded_dpi": None, "declared_dpi": None})
    specs = {"reference": (reference, "MISSING_REFERENCE"),
             "registration_metadata": (package / "version.json", "MISSING_METADATA"),
             "descriptors": (package / "descriptors.npz", "MISSING_METADATA"),
             "anchors": (package / "anchors.json", "MISSING_METADATA"),
             "fields": (package / "fields.json", "MISSING_METADATA")}
    row["assets"] = {name: asset(path, missing) for name, (path, missing) in specs.items()}
    row["assets"]["safe_cells"] = {
        "path": None, "sha256": None, "status": "MISSING_SAFE_CELLS",
        "reason": "No standalone safe-cell file is configured or required by the current registration loader; GeometryRequest supplies source_cell at runtime. A separate asset cannot be certified.",
    }
    row["inline_anchors"] = {"path": str(definition), "sha256": row["definition"]["sha256"],
                             "status": "READY" if template.anchor_definitions else "MISSING_METADATA",
                             "count": len(template.anchor_definitions),
                             "anchors": [a.model_dump(mode="json") for a in template.anchor_definitions]}
    metadata = None
    if specs["registration_metadata"][0].is_file():
        try:
            metadata = CanonicalTemplateMetadata.model_validate_json(
                specs["registration_metadata"][0].read_text(encoding="utf-8"))
            row["registration_metadata"] = metadata.model_dump()
            row["resolution"]["declared_dpi"] = metadata.expected_dpi
        except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
            row["assets"]["registration_metadata"]["status"] = "INVALID_METADATA"
            row["issues"].append(str(exc))
    if reference.is_file():
        try:
            with Image.open(reference) as image:
                image.load()
                row["reference_dimensions"] = list(image.size)
                row["resolution"]["embedded_dpi"] = image.info.get("dpi")
                expected = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
                if image.size != expected:
                    row["assets"]["reference"]["status"] = "INVALID_REFERENCE"
                    row["issues"].append("Reference dimensions differ from template dimensions")
            if metadata and row["assets"]["reference"]["sha256"] != metadata.image_sha256:
                row["assets"]["reference"]["status"] = "INVALID_REFERENCE"
                row["issues"].append("Reference hash does not match registration metadata")
        except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
            row["assets"]["reference"]["status"] = "CORRUPT"
            row["issues"].append(str(exc))
    expected_json = {
        "anchors": [a.model_dump(mode="json") for a in template.anchor_definitions],
        "fields": {"reference_dimensions": template.reference_dimensions.model_dump(mode="json"),
                   "field_regions": [f.model_dump(mode="json") for f in template.field_regions],
                   "service_line_region": template.service_line_region.model_dump(mode="json")
                   if template.service_line_region else None},
    }
    for name, expected in expected_json.items():
        path = specs[name][0]
        if path.is_file():
            try:
                if json.loads(path.read_text(encoding="utf-8")) != expected:
                    row["assets"][name]["status"] = "INVALID_METADATA"
                    row["issues"].append(name + " differs from registered definition")
            except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
                row["assets"][name]["status"] = "CORRUPT"
                row["issues"].append(str(exc))
    descriptor = specs["descriptors"][0]
    if descriptor.is_file():
        try:
            with np.load(descriptor, allow_pickle=False) as data:
                points, features = data["keypoints"], data["descriptors"]
                row["descriptor_shapes"] = {"keypoints": list(points.shape), "descriptors": list(features.shape)}
                valid = (points.ndim == 2 and points.shape[1] == 2 and features.shape == (len(points), 128)
                         and np.isfinite(points).all() and np.isfinite(features).all())
                if metadata:
                    valid = valid and len(points) == metadata.descriptor_keypoint_count
                    valid = valid and row["assets"]["descriptors"]["sha256"] == metadata.descriptor_sha256
                if not valid:
                    row["assets"]["descriptors"]["status"] = "INVALID_METADATA"
        except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
            row["assets"]["descriptors"]["status"] = "CORRUPT"
            row["issues"].append(str(exc))
    row["runtime_canonical_load"] = "UNAVAILABLE"
    if package.is_dir() and template.reference_image_path is None:
        try:
            image = load_canonical_image(package, template)
            image.close()
            row["runtime_canonical_load"] = "PASS"
        except Exception as exc:  # noqa: BLE001 -- an invalid asset must not prevent auditing other templates
            row["runtime_canonical_load"] = "FAIL"
            if all(item["status"] == "READY" for name, item in row["assets"].items() if name != "safe_cells"):
                row["assets"]["registration_metadata"]["status"] = "INVALID_METADATA"
            row["issues"].append(str(exc))
    statuses = [value["status"] for value in row["assets"].values()]
    row["statuses"] = sorted(set(statuses) - {"READY"}) or ["READY"]
    row["status"] = next((status for status in ("CORRUPT", "MISSING_REFERENCE", "INVALID_REFERENCE",
                          "INVALID_METADATA", "MISSING_METADATA", "INVALID_SAFE_CELLS", "MISSING_SAFE_CELLS")
                          if status in statuses), "READY")
    return row


def locate_copies(roots):
    result = subprocess.run(["rg", "--files", "--hidden", "--no-ignore", *map(str, roots),
                             "-g", "*ub04*", "-g", "*UB04*", "-g", "*ub-04*", "-g", "*UB-04*",
                             "-g", "canonical.png", "-g", "M047IJBF.001"],
                            capture_output=True, text=True, check=False)
    copies = []
    for name in result.stdout.splitlines():
        path = Path(name)
        if (path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf", ".npz", ".001"}
                and ("ub04" in name.lower() or "ub-04" in name.lower() or path.name == "M047IJBF.001")):
            item = asset(path, "MISSING_REFERENCE")
            item["eligibility"] = "UNVERIFIED_COPY_NOT_ACTIVATED"
            if path.name == "M047IJBF.001":
                item["eligibility"] = "RAW_CLAIM_SOURCE_NOT_APPROVED_REFERENCE"
            if "reference_images" in path.parts:
                item["kind"] = "EXISTING_REFERENCE_COPY"
                try:
                    with Image.open(path) as image:
                        image.load()
                        item["dimensions"] = list(image.size)
                        item["embedded_dpi"] = image.info.get("dpi")
                        item["matches_registered_dimensions"] = image.size == (1711, 2216)
                except Exception as exc:  # noqa: BLE001 -- preserve a corrupt copy in the audit
                    item["status"] = "CORRUPT"
                    item["error"] = str(exc)
            copies.append(item)
    return {"roots": list(map(str, roots)), "method": "Filename search including ignored files; not a content/provenance certification",
            "exit_code": result.returncode, "errors": result.stderr, "copies": copies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    templates = [audit_template(path) for path in sorted((ROOT / "config/templates").glob("*.yaml"))]
    report = {"checked_at": datetime.now(UTC).isoformat(), "templates": templates,
              "certification": "FAIL" if any(row["status"] != "READY" for row in templates) else "PASS",
              "safe_cell_certification_note": "Standalone safe-cell assets are not part of the current loader contract. This requested check fails certification, but is not evidence of a pre-registration runtime blocker.",
              "ub04_search": locate_copies(args.search_root or [ROOT.parent])}
    trace_path = ROOT / "runs/application-5b7b689e0fa843e9914d6e9640b28613/document.json"
    if trace_path.is_file():
        recorded = json.loads(trace_path.read_text(encoding="utf-8"))
        report["recorded_execution"] = {"source": asset(trace_path, "MISSING_METADATA"),
                                        "stages": recorded["stages"], "cms1500_rejections": []}
        for candidate in recorded["template_selection"]["candidate_templates"]:
            evidence = candidate.get("diagnostics", {}).get("registration_evidence")
            if candidate["template_id"] == "cms1500" and evidence:
                report["recorded_execution"]["cms1500_rejections"].append({"page": candidate["page_number"],
                    "evidence": evidence, "policy": candidate["diagnostics"].get("registration_policy")})
    report["findings"] = [
        "UB04 reference_image_path is null and templates/ub04 is absent: no reference can resolve through the registered loader.",
        "CMS1500 safety rejections are recorded transform/lineage failures; a valid asset checksum does not prove compatibility with this scanned form.",
        "No corrupt CMS1500 asset or DPI mismatch may be inferred solely from a rejected transform. PNG DPI may be absent despite declared DPI metadata.",
        "The recorded execution says template selection UNAVAILABLE, not SUCCESS.",
    ]
    report["recommended_fix"] = [
        "Provision a provenance-approved UB04 2014 reference package or configure an approved existing reference through the existing loader; do not substitute a claim scan automatically.",
        "Have the asset owner verify CMS1500 reference lineage against the source form revision and calibration; preserve thresholds until compatibility is established.",
        "Clarify the required safe-cell asset contract; fields.json contains field regions, not a separately certified safe-cell file.",
    ]
    for root in args.search_root:
        for archive_name in ("Hackathon - 1000 Claims.zip", "Images & Output.zip"):
            path = root / archive_name
            if path.is_file():
                with ZipFile(path, "r") as archive:
                    for entry in archive.infolist():
                        if entry.filename.replace("\\", "/").endswith("Group C/M047IJBF.001"):
                            with archive.open(entry) as stream:
                                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                            report["ub04_search"]["copies"].append({"path": str(path), "entry": entry.filename,
                                "sha256": digest, "eligibility": "RAW_CLAIM_SOURCE_NOT_APPROVED_REFERENCE"})
    if not report["ub04_search"]["copies"]:
        report["ub04_search"]["result"] = "MISSING_RUNTIME_ASSET"
    else:
        report["ub04_search"]["result"] = "UNVERIFIED_COPIES_FOUND_RUNTIME_ASSET_STILL_MISSING"
    report["missing_assets"] = [
        {"template_id": row["template_id"], "asset": name, **item}
        for row in templates for name, item in row["assets"].items()
        if item["status"].startswith("MISSING_")
    ]
    report["existing_reference_copies"] = [item for item in report["ub04_search"]["copies"]
                                            if item.get("kind") == "EXISTING_REFERENCE_COPY"]
    payload = json.dumps(report, indent=2)
    (ROOT / "registration_assets.json").write_text(payload + "\n", encoding="utf-8")
    lines = ["Registration Asset Check", "Templates"]
    for row in templates:
        lines.append(f'{row["template_id"]}@{row["template_version"]}: {row["status"]}')
        for name, item in row["assets"].items():
            lines.append(f'  {name}: {"PASS" if item["status"] == "READY" else "FAIL"} — {item["status"]}')
        if "inline_anchors" in row:
            lines.append(f'  inline_anchor_metadata: {"PASS" if row["inline_anchors"]["status"] == "READY" else "FAIL"} - {row["inline_anchors"]["count"]} definitions')
    lines.append("Safe-cell FAIL means no standalone certifiable file; it is not a required registration input.")
    lines.append(report["certification"])
    text = "\n".join(lines) + "\n"
    (ROOT / "doctor_report.txt").write_text(text, encoding="utf-8")
    (ROOT / "registration_assets.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Registration assets</title>'
        '<body><h1>Registration Asset Certification</h1><pre>' + escape(text)
        + '</pre><h2>Assets, hashes and findings</h2><pre>' + escape(payload) + '</pre></body></html>', encoding="utf-8")
    print(text)
    return 0 if report["certification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
