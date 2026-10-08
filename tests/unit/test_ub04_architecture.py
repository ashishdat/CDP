import numpy as np
import pytest
from PIL import Image
from packages.templates.registry import TemplateRegistry
from packages.extraction_recovery.ub04_registered import validate_landmark,extract_registered_ub04
from packages.extraction_recovery.independent_case_router import classify_independent_case,CasePath
from packages.evaluation.family_metrics import family_metrics


def geometry(template):
    return {"status":"SUCCESS","coordinate_frame":"rectified_template_pixels","fields":[
        {"field":r.field_name,"result":{"aligned_roi":{k:getattr(r,k) for k in ("x0","y0","x1","y1")}}} for r in template.field_regions]}


def test_registered_ub04_route_does_not_use_cms_residuals():
    text="UB-04 CMS-1450 TYPE OF BILL STATEMENT COVERS PERIOD"
    assert classify_independent_case(text,registration_ok=True).path == CasePath.UB04_GEOMETRY
    assert classify_independent_case(text,registration_ok=True,field_ink_hitl=True).path == CasePath.UB04_GEOMETRY
    assert classify_independent_case(text,registration_ok=False).path == CasePath.UNSTRUCTURED_DI


def test_public_variant_crops_are_not_sample_scan_crops():
    registry=TemplateRegistry.load_from_directory()
    old=registry.get("ub04","2014");new=registry.get("ub04","2014-public-v2")
    assert old.field_region("patient_dob").y0 != new.field_region("patient_dob").y0
    image=registry.load_reference_image(new)
    assert image.size == (1711,2216)
    seen=[]
    rows,lines,checks=extract_registered_ub04(image,geometry(new),new,image,lambda n,b,k:(seen.append((n,b)) or [],[],"TEST"))
    assert not checks["critical_fields_blocked"]
    assert {"patient_name","patient_dob","insured_id_number","total_charge","provider_npi","type_of_bill","federal_tax_no"} <= set(n for n,b in seen)
    assert lines==[] and checks["service_rows_examined"]==22
    assert all(not r["cascade"]["accepted"] for r in rows)


def test_local_alignment_blocks_shifted_or_missing_print():
    registry=TemplateRegistry.load_from_directory();template=registry.get("ub04","2014-public-v2")
    blank=registry.load_reference_image(template)
    import yaml
    from packages.extraction_recovery.ub04_registered import ROOT
    box=yaml.safe_load((ROOT/"config/ub04_registered_v2.yaml").read_text())["landmarks"]["patient_dob"]
    assert validate_landmark(blank,blank,box)["accepted"]
    shifted=Image.fromarray(np.roll(np.asarray(blank),8,axis=1))
    assert not validate_landmark(shifted,blank,box)["accepted"]
    assert not validate_landmark(Image.new("L",blank.size,255),blank,box)["accepted"]
    called=[]
    rows,_,checks=extract_registered_ub04(shifted,geometry(template),template,blank,lambda *a:(called.append(a) or [],[],"TEST"))
    assert checks["critical_fields_blocked"] and not called
    assert all(not r["candidates"] for r in rows)


def test_stale_template_never_reads_crops():
    registry=TemplateRegistry.load_from_directory();template=registry.get("ub04","2014")
    blank=registry.load_reference_image(template)
    rows,lines,checks=extract_registered_ub04(blank,geometry(template),template,blank,lambda *a:pytest.fail("Unqualified crop read"))
    assert not checks["binding_qualified"] and not lines
    assert all(not r["candidates"] for r in rows)


def test_family_metrics_use_all_inputs_and_independent_hash_bound_labels():
    row={"document":"a","claim_id":"a","finished":True,"completed":True,"true_stp":True,"document_family":"UB04","source_sha256":"hash","fields":{"insured_id_number":{"disp":"AUTO_ACCEPTED","value":"0012"}}}
    truth={"claims":{"a":{"source_sha256":"hash","fields":{"insured_id_number":{"value":"012","verification_status":"OPERATOR_SUPPLIED_VERIFIED"}}}}}
    result=family_metrics([row,row],selected_count=2,truth=truth)
    assert result["overall"]["stp_rate_of_all"]==.5
    assert result["overall"]["verified_false_accepts"]==1
    row["source_sha256"]="different"
    result=family_metrics([row],truth=truth)
    assert result["overall"]["verified_accepted_fields_scored"]==0
    assert result["overall"]["unlabeled_accepted_critical_fields"]>=1
    assert not result["overall"]["zero_false_accepts_established"]


def test_finish_rejects_wrong_family_before_any_stage(tmp_path):
    import json
    from scripts.finish_from_ocr import run
    saved=tmp_path/"ocr.json";saved.write_text(json.dumps({"template_id":"ub04","template_version":"2014-public-v2","document_family":"UB04"}))
    with pytest.raises(ValueError,match="conflicts"):
        run(saved,tmp_path/"out",document_family="CMS1500")


@pytest.mark.parametrize("turns",[1,2,3])
def test_orientation_recovery_preserves_original_pixel_transform(turns):
    import cv2
    from workers.page_detection.template_alignment import align_to_reference
    registry=TemplateRegistry.load_from_directory();reference=registry.load_reference_image(registry.get("ub04","2014-public-v2"))
    # Smaller public blank retains static landmarks while keeping this regression bounded.
    reference=reference.resize((856,1108))
    source=Image.fromarray(np.ascontiguousarray(np.rot90(np.asarray(reference),turns)))
    result=align_to_reference(source,reference,enforce_compatibility_precheck=False)
    assert result.accepted
    restored=cv2.warpPerspective(np.asarray(source),result.homography,reference.size,borderValue=255)
    assert np.abs(restored.astype(float)-np.asarray(reference).astype(float)).mean()<5
    assert result.evidence.orientation_normalization_degrees in {90,180,270}
    assert np.allclose(result.evidence.transform_matrix,result.homography)


def test_spatial_anchor_matching_rejects_unrelated_boxes():
    from workers.page_detection.anchor_matching import verify_anchors
    from workers.page_detection.text_extraction import TextLine
    from packages.templates.models import AnchorDefinition
    lines=[TextLine(text="TYPE",x0=0,y0=0,x1=30,y1=20,confidence=1),
           TextLine(text="OF BILL",x0=900,y0=900,x1=1000,y1=920,confidence=1)]
    assert not verify_anchors(lines,[AnchorDefinition(phrase="TYPE OF BILL")]).all_required_matched


def test_cell_frame_rejects_local_warp_even_when_caption_remains():
    from packages.extraction_recovery.ub04_registered import validate_cell_frame,ROOT
    import yaml
    registry=TemplateRegistry.load_from_directory();blank=registry.load_reference_image(registry.get("ub04","2014-public-v2"))
    box=yaml.safe_load((ROOT/"config/ub04_registered_v2.yaml").read_text())["frame_landmarks"]["patient_dob"]
    assert validate_cell_frame(blank,blank,box)["accepted"]
    shifted=Image.fromarray(np.roll(np.asarray(blank),8,axis=1))
    assert not validate_cell_frame(shifted,blank,box)["accepted"]



def test_ub04_table_keeps_sparse_rows_and_excludes_totals_row():
    registry=TemplateRegistry.load_from_directory();template=registry.get("ub04","2014-public-v2")
    blank=registry.load_reference_image(template);pixels=np.asarray(blank).copy();table=template.service_line_region
    for index in (0,11,21):
        y=round(table.table_y0+(table.table_y1-table.table_y0)*index/table.max_rows)+8
        pixels[y:y+7,200:220]=0
    seen=[]
    rows,lines,checks=extract_registered_ub04(Image.fromarray(pixels),geometry(template),template,blank,
        lambda n,b,k:(seen.append(n) or [],[],"TEST"))
    assert [line["row_number"] for line in lines]==[1,12,22]
    assert all(line["schema_version"]=="ub04-service-lines-v1" and line["financial_authority"] is False for line in lines)
    assert all(set(line["cells"])=={"revenue_code","description","hcpcs_rate","service_date","service_units","total_charges","non_covered_charges"} for line in lines)
    assert checks["service_rows_examined"]==22


def test_ub04_id_has_explicit_required_governance():
    from packages.field_policy import FieldPolicyRegistry
    policy=FieldPolicyRegistry.load().for_field("UB04","insured_id_number")
    assert policy.required and policy.blocks_stp
    total=FieldPolicyRegistry.load().for_field("UB04","total_charge")
    assert total.required and total.blocks_stp and total.criticality.value == "C3"


def test_small_printed_ruling_shift_does_not_create_service_lines():
    registry=TemplateRegistry.load_from_directory();template=registry.get("ub04","2014-public-v2")
    blank=registry.load_reference_image(template)
    shifted=Image.fromarray(np.roll(np.asarray(blank),1,axis=1))
    _,lines,checks=extract_registered_ub04(shifted,geometry(template),template,blank,
        lambda *args:([],[],"TEST"))
    assert checks["landmarks"]["service_lines"]["accepted"]
    assert checks["service_rows_examined"] == 22
    assert lines == []
    assert len(checks["service_row_activity"]) == 22



def test_finish_uses_registered_cms_family_when_classification_text_is_unknown(tmp_path,monkeypatch):
    import json
    from scripts import finish_from_ocr as finish
    saved=tmp_path/"ocr.json";saved.write_text(json.dumps({"template_id":"cms1500","template_version":"03","document_family":"UNKNOWN"}))
    called=[]
    monkeypatch.setattr(finish,"rank_saved",lambda *a:None)
    monkeypatch.setattr(finish,"validate_run",lambda *a:called.append((a[2],a[3])))
    monkeypatch.setattr(finish,"assemble",lambda *a:None)
    monkeypatch.setattr(finish,"complete_run",lambda *a:(called.append(a[2]) or {"status":"COMPLETED","review_required":False}))
    assert finish.run(saved,tmp_path/"out")["true_stp"]
    assert called==[("cms1500","03"),"CMS1500"]



def test_sparse_stp_ledger_cannot_establish_zero_false_accepts():
    row={"document":"a","claim_id":"a","finished":True,"completed":True,"true_stp":True,"source_sha256":"hash","fields":{"insured_id_number":{"disp":"AUTO_ACCEPTED","value":"0012"}}}
    truth={"claims":{"a":{"source_sha256":"hash","fields":{"insured_id_number":{"value":"0012","verification_status":"OPERATOR_SUPPLIED_VERIFIED"}}}}}
    result=family_metrics([row],truth=truth)["overall"]
    assert result["verified_accepted_fields_scored"]==1 and result["verified_false_accepts"]==0
    assert result["missing_accepted_critical_field_records"]==3
    assert not result["zero_false_accepts_established"]



def test_run_contract_pins_nested_versioned_template_assets(tmp_path):
    from scripts.run_hackathon_1000_cascade import _independent_run_contract
    dataset=tmp_path/"dataset.yaml";dataset.write_text("synthetic: true\n")
    hashes=_independent_run_contract(dataset,"AUTO",{})["template_asset_sha256"]
    normalized={name.replace("\\","/") for name in hashes}
    for name in ["canonical.png","version.json","descriptors.npz","anchors.json","fields.json"]:
        assert "templates/ub04/2014-public-v2/"+name in normalized
