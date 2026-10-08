"""Evaluation-only family report; verified labels never enter inference."""
import argparse,json,hashlib
from pathlib import Path
from packages.evaluation.family_metrics import family_metrics


def evaluate(run,selected_count,truth_path=None):
    run=Path(run);rows=[]
    for line in (run/"results.jsonl").read_text(encoding="utf-8").splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:continue
        ocr_path=run/"claims"/str(row.get("claim_id"))/"ocr/OCRCandidates.json"
        if ocr_path.is_file():
            saved=json.loads(ocr_path.read_text(encoding="utf-8"))
            row={**row,"source_sha256":saved.get("document_id"),"document_family":saved.get("document_family") or row.get("document_family")}
        final_path=run/"claims"/str(row.get("claim_id"))/"final/FinalClaim.json"
        if final_path.is_file():
            final=json.loads(final_path.read_text(encoding="utf-8"))
            final_hash=(final.get("document") or {}).get("document_id")
            if row.get("source_sha256") and final_hash != row["source_sha256"]:
                raise ValueError("Final/OCR source identity mismatch")
            decisions=(final.get("decision") or final).get("field_decisions") or []
            row={**row,"source_sha256":final_hash,"fields":{f["field_name"]:{
                "disp":f.get("disposition"),"value":f.get("selected_value")} for f in decisions}}
        rows.append(row)
    truth=None
    if truth_path:
        truth=json.loads(Path(truth_path).read_text(encoding="utf-8"))
        if truth.get("schema_version") != "source-bound-verified-labels-v1" or truth.get("runtime_use_allowed") is not False:
            raise ValueError("Only evaluation-only source-bound operator-verified labels are supported")
    result=family_metrics(rows,selected_count=selected_count,truth=truth)
    result["verified_label_artifact_sha256"]=hashlib.sha256(Path(truth_path).read_bytes()).hexdigest() if truth_path else None
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("run",type=Path);parser.add_argument("--selected-count",type=int,required=True);parser.add_argument("--truth",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    result=evaluate(args.run,args.selected_count,args.truth);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result["overall"]))
