"""Fresh native extraction on approved originals using saved accepted geometry."""
import json
import argparse
import os
from pathlib import Path
import subprocess
from scripts import benchmark_hackathon_four_corpora as benchmark

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-root",type=Path,default=ROOT / "evaluation_results/current_review_repairs")
    parser.add_argument("--python",type=Path,default=ROOT.parent.parent / ".venv-ocr/Scripts/python.exe")
    parser.add_argument("--timeout",type=float,default=300)
    args=parser.parse_args()
    out = args.output_root;out.mkdir(parents=True,exist_ok=True)
    inventory = json.loads((ROOT / "evaluation_results/current_review_repairs/inventory.json").read_text())
    manifest = json.loads((ROOT / "evaluation_results/regression50_v311_20261006/benchmark_manifest.json").read_text())
    env = benchmark.run_env(out, manifest["corpora"][0]["sample_archive"], "LOCAL_ONLY")
    env["PYTHONPATH"] = str(ROOT)+os.pathsep+env.get("PYTHONPATH", "")
    python = args.python
    results = []
    for case in inventory["cases"]:
        if case["family"] != "UB04":
            continue
        source = Path(case["artifact"]) / "ocr/OCRCandidates.json"
        saved = json.loads(source.read_text())
        target = out / "final_native" / case["document"].replace("/", "__")
        target.mkdir(parents=True, exist_ok=True)
        command = [str(python), "-c",
            "import os,json,sys; from scripts.ocr_from_geometry import run; "
            "from scripts.finish_from_ocr import run as finish; "
            "from pathlib import Path; "
            "r=run(sys.argv[1],sys.argv[2]); f=finish(Path(sys.argv[2])/'OCRCandidates.json',Path(sys.argv[2]).parent); "
            "print(json.dumps(f),flush=True); os._exit(0)",
            str(Path(saved["geometry_reference"]).parent), str(target / "ocr")]
        with (target / "native.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            timed_out=False
            try:
                process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                if os.name == "nt":
                    subprocess.run([str(Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/taskkill.exe"),
                        "/PID",str(process.pid),"/T","/F"],stdout=log,stderr=subprocess.STDOUT,check=False)
                if process.poll() is None:
                    process.kill()
                process.wait()
        row = {"document": case["document"], "returncode": 124 if timed_out else process.returncode,
               "timed_out":timed_out,
               "scope": "Fresh LOCAL_ONLY native OCR and governed completion; saved accepted homography, original source hash checked; no new registration or cloud calls."}
        results.append(row)
        (out / "final_native_verification.json").write_text(json.dumps(results, indent=2))
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
