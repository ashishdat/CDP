"""Local-only deduplicated layout audit. Never create references from claim scans."""
import argparse,json,hashlib
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from collections import Counter
import cv2
import numpy as np
from PIL import Image
from packages.templates.registry import TemplateRegistry
from packages.extraction_recovery.ub04_registered import validate_landmark,validate_cell_frame,ROOT
import yaml


def audit(roots):
    registry=TemplateRegistry.load_from_directory()
    cfg=yaml.safe_load((ROOT/"config/ub04_registered_v2.yaml").read_text(encoding="utf-8"))
    selected_sources={}
    for root in roots:
        for manifest_path in Path(root).glob("benchmark_manifest.json"):
            manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
            for corpus in manifest.get("corpora",[]):
                archive_path=corpus.get("sample_archive") or corpus.get("archive")
                if archive_path:
                    for entry in corpus.get("documents",[]):
                        selected_sources.setdefault(entry,[]).append(archive_path)
    records={}; errors=[]; duplicates=0
    for root in roots:
        for path in Path(root).rglob("GeometryResult.json"):
            try:
                geometry=json.loads(path.read_text(encoding="utf-8"))
                if geometry.get("status") != "SUCCESS":continue
                telemetry_path=path.parent/"geometry_telemetry.json"
                identity_basis="SAVED_GEOMETRY_TELEMETRY"
                if telemetry_path.is_file():
                    telemetry=json.loads(telemetry_path.read_text(encoding="utf-8"));source=telemetry["source"]
                else:
                    saved=json.loads((path.parents[2]/"ocr/OCRCandidates.json").read_text(encoding="utf-8"))
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=saved["geometry_sha256"]:
                        raise ValueError("Saved OCR geometry hash mismatch")
                    entry=path.parents[2].name.replace("__","/")
                    archives=selected_sources.get(entry,[])
                    source=None
                    for archive_path in archives:
                        if not Path(archive_path).is_file():continue
                        with ZipFile(archive_path) as archive: candidate=archive.read(entry)
                        if hashlib.sha256(candidate).hexdigest()==saved["document_id"]:
                            source={"archive":archive_path,"entry":entry};break
                    if source is None:raise ValueError("No source-hash-bound selection archive")
                    telemetry={"document_id":saved["document_id"]}
                    identity_basis="HASH_BOUND_OCR_AND_SELECTION_MANIFEST"
                with ZipFile(source["archive"]) as archive:payload=archive.read(source["entry"])
                digest=hashlib.sha256(payload).hexdigest()
                if digest != telemetry["document_id"]:raise ValueError("Source identity mismatch")
                key=(digest,geometry["page_number"])
                if key in records:duplicates+=1;continue
                with Image.open(BytesIO(payload)) as document:
                    document.seek(geometry["page_number"]-1); page=document.convert("L")
                tid=geometry["template_id"];template=registry.get(tid,geometry["template_version"])
                # Existing accepted UB transforms target the same official blank.
                reference=registry.load_reference_image(template)
                matrix=np.asarray(geometry["source_to_geometry_transform"],dtype=float)
                rectified=Image.fromarray(cv2.warpPerspective(np.asarray(page),matrix,reference.size,borderValue=255))
                checks={}
                if tid == "ub04":
                    checks={name:validate_landmark(rectified,reference,box) for name,box in cfg["landmarks"].items()}
                    for name,box in cfg.get("frame_landmarks",{}).items():
                        frame=validate_cell_frame(rectified,reference,box)
                        checks[name]={**checks.get(name,{}),"cell_frame":frame,
                            "accepted":bool(checks.get(name,{}).get("accepted") or frame.get("accepted"))}
                records[key]={"source_sha256":digest,"document":source["entry"],"page_number":geometry["page_number"],
                    "source_identity_basis":identity_basis,"family":"UB04" if tid=="ub04" else "CMS1500","template_id":tid,"template_version":geometry["template_version"],
                    "source_dimensions":list(page.size),"local_landmarks":checks,
                    "layout_status":"LOCAL_LANDMARKS_MATCH" if checks and all(c["accepted"] for c in checks.values()) else "REQUIRES_LOCAL_LAYOUT_REVIEW" if checks else "CMS_BINDING_ONLY_NOT_FIELD_VALIDATION"}
            except (OSError,KeyError,ValueError,TypeError) as exc:
                errors.append({"artifact":str(path),"reason":str(exc)})
    registered_count=len(records)
    # Include selected but unregistered pages so successful registrations do
    # not hide the layouts most in need of investigation.
    selected_keys=set()
    for root in roots:
        for manifest_path in Path(root).glob("benchmark_manifest.json"):
            manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
            for corpus in manifest.get("corpora",[]):
                archive_path=corpus.get("sample_archive") or corpus.get("archive")
                if not archive_path or not Path(archive_path).is_file():continue
                with ZipFile(archive_path) as archive:
                    for entry in corpus.get("documents",[]):
                        payload=archive.read(entry);digest=hashlib.sha256(payload).hexdigest()
                        with Image.open(BytesIO(payload)) as document:
                            for page in range(1,document.n_frames+1):
                                key=(digest,page);selected_keys.add(key)
                                if key in records:continue
                                document.seek(page-1)
                                records[key]={"source_sha256":digest,"document":entry,"page_number":page,
                                    "family":"UNKNOWN","source_dimensions":list(document.size),
                                    "layout_status":"NO_REGISTERED_LAYOUT_EVIDENCE","local_landmarks":{}}
    return {"unique_document_pages":len(records),"unique_documents":len({key[0] for key in records}),"registered_unique_pages":registered_count,
        "selected_unique_pages":len(selected_keys),"duplicate_artifacts_excluded":duplicates,
        "family_counts":dict(Counter(r["family"] for r in records.values())),"records":list(records.values()),"errors":errors,
        "new_canonical_variants_created":0,"qualification":"Deduplicated development artifacts, not an independent holdout. Add variants only after static-layout review; low landmark score can also mean scan damage or residual alignment error."}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("roots",nargs="+",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    result=audit(args.roots);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"records","errors"}}));print("audit_errors",len(result["errors"]))
