"""Compare hash-bound source regressions; evaluation labels never enter inference."""
import argparse,json
from pathlib import Path
from packages.evaluation.family_metrics import family_metrics

def load_cases(root):
    cases={}
    for path in Path(root).glob("*/final/FinalClaim.json"):
        final=json.loads(path.read_text(encoding="utf-8"));decision=final.get("decision") or final
        cases[path.parents[1].name]={"source_sha256":final["document"]["document_id"],"claim_status":decision.get("claim_status"),
            "fields":{f["field_name"]:{"disp":f["disposition"],"value":f.get("selected_value"),"reasons":f.get("reason_codes",[])}for f in decision["field_decisions"]}}
    return cases

def audit(before_root,after_root,truth=None):
    before,after=load_cases(before_root),load_cases(after_root);pairs=[];rows=[]
    if not before or set(before)!=set(after):
        raise ValueError("Incomplete matched source regression: both sides must finish every case")

    for case in sorted(set(before)&set(after)):
        a,b=after[case],before[case]
        if a["source_sha256"]!=b["source_sha256"]:raise ValueError("Before/after source identity mismatch: "+case)
        pairs.append({"case":case,"source_sha256":a["source_sha256"],"before_claim":b["claim_status"],"after_claim":a["claim_status"],
            "field_changes":{name:{"before":b["fields"].get(name),"after":field}for name,field in a["fields"].items()if field!=b["fields"].get(name)}})
        stp=a["claim_status"]=="STP_SAFE"
        rows.append({"document":case.replace("__","/"),"claim_id":case,"finished":True,"completed":True,"registration_ok":True,
            "document_family":"CMS1500","true_stp":stp,"disposition":"TRUE_STP"if stp else "HITL",**a})
    return {"matched_cases":len(pairs),"missing_before_cases":sorted(set(after)-set(before)),"missing_after_cases":sorted(set(before)-set(after)),
        "pairs":pairs,"evaluation":family_metrics(rows,selected_count=len(after),truth=truth),
        "qualification":"Matched source identity is required. Caller must establish matching runtime profiles and distinguish full pipeline tests from partial field replay."}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("before",type=Path);parser.add_argument("after",type=Path);parser.add_argument("--truth",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    truth=json.loads(args.truth.read_text(encoding="utf-8"))if args.truth else None
    if truth and (truth.get("schema_version")!="source-bound-verified-labels-v1" or truth.get("runtime_use_allowed")is not False):raise ValueError("Evaluation-only source-bound verified labels required")
    report=audit(args.before,args.after,truth);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"matched_cases":report["matched_cases"],"evaluation":report["evaluation"]["overall"]}))
