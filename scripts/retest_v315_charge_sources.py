"""Fresh DI charge acquisition and governed completion on approved originals."""
import io,json,os,hashlib
import shutil
from pathlib import Path
from zipfile import ZipFile
import cv2
import numpy as np
from PIL import Image
from packages.templates.registry import TemplateRegistry
from packages.extraction_recovery.charge_azure_di_residual import run_charge_azure_di_residual,promote_currency_shaped,residual_candidate_dict
from scripts.ocr_from_geometry import _load_cms1500_template
from scripts.finish_from_ocr import run as finish


def main():
    from workers.ocr_engine_factories import wire_package_ocr_providers
    wire_package_ocr_providers()
    root=Path.cwd();out=root/"evaluation_results/v315_charge_retest";out.mkdir(exist_ok=True)
    results=[]
    for document in ["Group A__M048DJKN.022","Group A__M048DJKN.024","Group A__M048EJG7.002"]:
        source=root/"evaluation_results/regression50_v314_20261007/product/corpus_100/claims"/document/"ocr/OCRCandidates.json"
        saved=json.loads(source.read_text());directory=Path(saved["geometry_reference"]).parent
        geometry=json.loads((directory/"GeometryResult.json").read_text());telemetry=json.loads((directory/"geometry_telemetry.json").read_text())
        template=_load_cms1500_template(geometry,telemetry,directory)
        with TemplateRegistry.load_from_directory().load_reference_image(template) as reference:
            with ZipFile(telemetry["source"]["archive"]) as archive:payload=archive.read(telemetry["source"]["entry"])
            assert hashlib.sha256(payload).hexdigest() == telemetry["document_id"]
            with Image.open(io.BytesIO(payload)) as im:
                im.seek(geometry["page_number"]-1);pixels=np.asarray(im.convert("L"))
            image=Image.fromarray(cv2.warpPerspective(pixels,np.asarray(geometry["source_to_geometry_transform"]),reference.size,borderValue=255))
        case=out/"retry3"/document;case.mkdir(parents=True);ocrdir=case/"ocr";ocrdir.mkdir()
        total=next(row for row in saved["fields"] if row["field"] == "total_charge")
        box=tuple(total.get("ocr_region") or total["canonical_region"])
        acquired=run_charge_azure_di_residual(image=image,bbox=box,field_name="total_charge",
            gap_class="CHARGE_LOCAL_EXHAUSTED",corroborate=True)
        candidate=residual_candidate_dict(promote_currency_shaped(acquired),bbox=box,image_size=image.size)
        before_candidates=list(total.get("candidates") or [])
        total["candidates"]=[c for c in before_candidates if c.get("preprocessing_variant") != "charge_azure_di_crop_residual"]
        if candidate:total["candidates"].append(candidate)
        from dataclasses import asdict
        total["azure_di_residual"]={**asdict(acquired),"retest":True}
        (ocrdir/"OCRCandidates.json").write_text(json.dumps(saved,indent=2))
        shutil.copy2(source.parent/"ocr_telemetry.json",ocrdir/"ocr_telemetry.json")
        (case/"fresh_di_result.json").write_text(json.dumps(asdict(acquired),indent=2))
        decision=finish(ocrdir/"OCRCandidates.json",case)
        row={"document":document,"source_sha256":telemetry["document_id"],
            "fresh_di_result":asdict(acquired),"candidate":candidate,"decision":decision,
            "scope":"Fresh approved DI charge crop; other fields and service lines replayed from completed v3.14. Governed finish; not a fresh full pipeline run."}
        results.append(row);(out/"retry3_results.json").write_text(json.dumps(results,indent=2))
        print(json.dumps({"document":document,"reason":acquired.reason,"value":acquired.value,"decision":decision}),flush=True)


if __name__ == "__main__":main()
