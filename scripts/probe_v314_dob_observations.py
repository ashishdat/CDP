import io
import json
import hashlib
from pathlib import Path
from zipfile import ZipFile
import cv2
import numpy as np
from PIL import Image
import pytesseract
from packages.templates.registry import TemplateRegistry
from scripts.ocr_from_geometry import _load_cms1500_template,_recognize_dob_cells_for_engine


def main():
    pytesseract.pytesseract.tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    root=Path.cwd();results=[]
    for corpus,document in [(1000,"Group A__M048DJJM.010"),(100,"Group A__M048EJG7.002")]:
        source=root/f"evaluation_results/regression50_v311_20261006/product/corpus_{corpus}/claims/{document}/ocr/OCRCandidates.json"
        saved=json.loads(source.read_text());directory=Path(saved["geometry_reference"]).parent
        geometry=json.loads((directory/"GeometryResult.json").read_text());telemetry=json.loads((directory/"geometry_telemetry.json").read_text())
        template=_load_cms1500_template(geometry,telemetry,directory)
        with TemplateRegistry.load_from_directory().load_reference_image(template) as reference:
            with ZipFile(telemetry["source"]["archive"]) as archive:
                payload=archive.read(telemetry["source"]["entry"])
            assert hashlib.sha256(payload).hexdigest() == telemetry["document_id"]
            with Image.open(io.BytesIO(payload)) as image:
                image.seek(geometry["page_number"]-1);pixels=np.asarray(image.convert("L"))
            image=Image.fromarray(cv2.warpPerspective(pixels,np.asarray(geometry["source_to_geometry_transform"]),reference.size,borderValue=255))
            region=template.field_region("patient_dob");bbox=tuple(getattr(region,k) for k in ("x0","y0","x1","y1"))
            candidates,attempts,reason=_recognize_dob_cells_for_engine(image,bbox,None,("tesseract",),canonical_cell=bbox)
            results.append({"document":document,"source_sha256":telemetry["document_id"],"reason":reason,
                "candidates":candidates,"attempts":attempts,"scope":"Fresh native component acquisition only; not full claim acceptance or independent accuracy."})
    (root/"evaluation_results/architecture_v314/native_dob_observations.json").write_text(json.dumps(results,indent=2))
    print(json.dumps([{ "document":r["document"],"reason":r["reason"],"candidate_count":len(r["candidates"])} for r in results]))


if __name__ == "__main__":
    main()
