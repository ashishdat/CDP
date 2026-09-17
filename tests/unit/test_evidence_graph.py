import copy
from hashlib import sha256
import json

import pytest
from scripts.evidence_graph import EvidenceGraph, pearson


def fixture(tmp_path):
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
    candidates = [{"raw_value": str(i), "raw_confidence": .8, "value": str(i)} for i in range(2)]
    checks = [{"field_id": "f", "candidate_id": f"f:{i}", "normalized_value": str(i), "status": "VALID"} for i in range(2)]
    winner = {"candidate_id": "f:0", "ocr_candidate": candidates[0]}
    field = {"field_name": "f", "ocr": {"candidates": candidates}, "candidate_validations": checks,
             "ranked_candidate": winner, "normalized_value": "0", "alternatives": []}
    geometry = {"page_number": 1, "status": "SUCCESS", "fields": [{"field": "f", "result": {"components": [{"area": 2},{"area": 3}], "alignment": None}}]}
    ref = write(tmp_path / "GeometryResult.json", geometry)
    extraction = {"type": "ExtractionResult", "status": "ASSEMBLED", "document": {"document_id": "doc"},
                  "page": {"page_number": 1}, "field_results": [field], "source_artifacts": {"geometry": ref}}
    path = tmp_path / "extraction" / "ExtractionResult.json"
    er = write(path, extraction)
    write(tmp_path / "DecisionResult.json", {"extraction_reference": er, "document": extraction["document"],
          "page": extraction["page"], "extracted_fields": [field], "deterministic_checks": {"f": {"status": "PASS", "evidence": ["FORMAT_VALID"]}},
          "claim_facts": {"evidence_items": [], "contradictions": []}, "field_decisions": []})
    write(tmp_path / "ApplicationResult.json", {"outputs": {"classification": {"document_id": "doc"},
          "registration": {"page_number": 1,"status": "SUCCESS", "template_id": "cms1500", "evidence": {"alignment_confidence": .7}, "selection": {"candidate_templates": []}}}})
    return path


def test_graph_keeps_observations_separate_and_shared_ancestry(tmp_path):
    path=fixture(tmp_path);before=path.read_bytes();g=EvidenceGraph();g.add_extraction(path);r=g.report()
    assert len([n for n in r["EvidenceNode"] if n["channel"]=="OCR"])==2
    assert len([n for n in r["EvidenceNode"] if n["channel"]=="Validator"])==2
    assert len([n for n in r["EvidenceNode"] if n["json_pointer"].startswith("/fields/0/result/components/")])==2
    assert r["metrics"]["agreement"]["disagreeing_pairs"]==1
    assert r["metrics"]["evidence_independence"]["proven_independent_pairs"]==0
    assert "Historical Pattern" in r["fields"][0]["missing_sources"]
    assert path.read_bytes()==before
    assert all(e["from"] in g.nodes and e["to"] in g.nodes for e in r["EvidenceEdge"])
    assert json.dumps(r,sort_keys=True)==json.dumps(g.report(),sort_keys=True)


def test_duplicate_claim_rejected(tmp_path):
    p=fixture(tmp_path);g=EvidenceGraph();g.add_extraction(p)
    with pytest.raises(ValueError,match="Duplicate"):
        g.add_extraction(p)


def test_tampered_artifact_rejected(tmp_path):
    p=fixture(tmp_path);(tmp_path/"GeometryResult.json").write_text("{}")
    with pytest.raises(ValueError,match="hash mismatch"):
        EvidenceGraph().add_extraction(p)


def test_decision_lineage_rejected(tmp_path):
    p=fixture(tmp_path);d=tmp_path/"DecisionResult.json";v=json.loads(d.read_text());v["page"]={"page_number":2};d.write_text(json.dumps(v))
    with pytest.raises(ValueError,match="lineage"):
        EvidenceGraph().add_extraction(p)


def test_correlation_does_not_invent_missing_or_constant_results():
    assert pearson([]) is None
    assert pearson([(1,2)]) is None
    assert pearson([(1,2),(1,3)]) is None
    assert pearson([(1,2),(2,4),(3,6)]) == pytest.approx(1)
    assert pearson([(1,6),(2,4),(3,2)]) == pytest.approx(-1)


def test_no_comparable_pairs_is_unavailable_not_agreement(tmp_path):
    p=fixture(tmp_path);g=EvidenceGraph();g.add_extraction(p);g.agreements=[]
    assert g.report()["metrics"]["agreement"]["agreement_percent"] is None
