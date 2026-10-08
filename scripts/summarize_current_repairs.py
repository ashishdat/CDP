import json
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-root",type=Path,default=Path.cwd() / "evaluation_results/current_review_repairs")
    out = parser.parse_args().output_root
    rows=[]
    for case in sorted((out / "final_native").iterdir()):
        ocr_path = case / "ocr/OCRCandidates.json"
        final_path = case / "final/FinalClaim.json"
        if not final_path.is_file():
            continue
        ocr=json.loads(ocr_path.read_text());final=json.loads(final_path.read_text())
        rows.append({"document":case.name.replace("__","/"),
                     "ocr_status":ocr["status"],"claim_status":final["claim_status"],
                     "stp_eligible":final["stp_eligible"],
                     "fields_with_candidates":[r["field"] for r in ocr["fields"] if r.get("candidates")],
                     "remaining_local_alignment_blockers":ocr["local_alignment"]["critical_fields_blocked"],
                     "service_rows_examined":ocr["local_alignment"]["service_rows_examined"],
                     "service_rows_observed":len(ocr["service_lines"]),
                     "source_sha256":ocr["document_id"]})
    (out / "native_outcomes.json").write_text(json.dumps({
        "scope":"Fresh local OCR and governed completion; saved accepted geometry; not a PRODUCT rerun or independent accuracy measurement.",
        "cases":rows},indent=2))
    print(json.dumps(rows,indent=2))


if __name__ == "__main__":
    main()
