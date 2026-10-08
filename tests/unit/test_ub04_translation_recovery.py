import numpy as np
from PIL import Image
from packages.extraction_recovery.ub04_registered import extract_registered_ub04
from packages.templates.registry import TemplateRegistry


def test_consistent_small_cell_offset_is_rechecked_and_recorded():
    registry=TemplateRegistry.load_from_directory();template=registry.get("ub04","2014-public-v2")
    reference=registry.load_reference_image(template)
    image=Image.fromarray(np.roll(np.roll(np.asarray(reference),4,axis=0),4,axis=1))
    geometry={"status":"SUCCESS","coordinate_frame":"rectified_template_pixels","fields":[
        {"field":r.field_name,"result":{"aligned_roi":{k:getattr(r,k) for k in ("x0","y0","x1","y1")}}}
        for r in template.field_regions]}
    seen=[]
    rows,_,_=extract_registered_ub04(image,geometry,template,reference,
        lambda name,box,kind:(seen.append((name,box)) or [],[],"OBSERVED"))
    recovered=[r for r in rows if r["local_alignment"].get("crop_translation_px") and r["local_alignment"].get("accepted")]
    assert recovered
    for row in recovered:
        local=row["local_alignment"]
        assert local["corrected_cell_frame"]["accepted"]
        assert max(map(abs,local["crop_translation_px"])) <= 6
        assert row["ocr_region"] != row["canonical_region"]
        assert (row["field"],tuple(row["ocr_region"])) in seen
        assert not row["cascade"]["accepted"]
    total=next(r for r in rows if r["field"] == "total_charge")
    assert not total["local_alignment"]["accepted"]
    assert not any(name == "total_charge" for name,_ in seen)
