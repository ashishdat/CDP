import json
import subprocess
import sys
from pathlib import Path
from scripts.run_hackathon_1000_cascade import _independent_run_contract


def main():
    root=Path.cwd();out=root/"evaluation_results/architecture_v314/final_control";out.mkdir(exist_ok=True)
    manifest=json.loads((root/"evaluation_results/regression50_v311_20261006/benchmark_manifest.json").read_text())
    dataset=Path(manifest["corpora"][0]["dataset"])
    settings={"profile":"LOCAL_ONLY","native_runtime":".venv-ocr-candidate-v314","cloud_calls":"0"}
    before=_independent_run_contract(dataset,"SAVED_ACCEPTED_GEOMETRY",settings)
    (out/"source_contract_before.json").write_text(json.dumps(before,indent=2))
    result=subprocess.run([sys.executable,"-m","scripts.verify_current_ub04_repairs",
        "--output-root",str(out),"--python",str(root.parent.parent/".venv-ocr-candidate-v314/Scripts/python.exe")],cwd=root,check=False)
    after=_independent_run_contract(dataset,"SAVED_ACCEPTED_GEOMETRY",settings)
    rows=json.loads((out/"final_native_verification.json").read_text())
    (out/"verification.json").write_text(json.dumps({"source_contract_unchanged":before == after,
        "driver_returncode":result.returncode,"all_native_controls_completed":len(rows)==3 and all(r["returncode"]==0 for r in rows),
        "scope":"Fresh local OCR and governed completion on three approved originals; saved accepted geometry, no new registration or cloud calls; not a PRODUCT cohort evaluation."},indent=2))


if __name__ == "__main__":
    main()
