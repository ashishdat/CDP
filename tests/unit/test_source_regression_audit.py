import json
import pytest
from scripts.audit_source_regression_outcomes import audit

def write_case(root,digest):
    p=root/"case/final";p.mkdir(parents=True)
    (p/"FinalClaim.json").write_text(json.dumps({"document":{"document_id":digest},"decision":{"claim_status":"FIELD_REVIEW_REQUIRED","field_decisions":[{"field_name":"patient_dob","disposition":"HUMAN_REVIEW_REQUIRED","selected_value":None}]}}))

def test_mismatched_source_images_cannot_be_compared(tmp_path):
    before=tmp_path/"before";after=tmp_path/"after"
    write_case(before,"source-a");write_case(after,"source-b")
    with pytest.raises(ValueError,match="identity mismatch"):audit(before,after)

def test_missing_case_cannot_be_hidden_by_intersection(tmp_path):
    before=tmp_path/"before";after=tmp_path/"after"
    write_case(before,"source-a");after.mkdir()
    with pytest.raises(ValueError,match="Incomplete"):audit(before,after)
