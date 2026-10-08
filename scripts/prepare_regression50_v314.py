"""Prepare the same authorized 50-input PRODUCT regression without inference."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
from datetime import UTC,datetime


def main():
    root=Path.cwd()
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",type=Path,default=root/"evaluation_results/regression50_v311_20261006")
    parser.add_argument("--output",type=Path,default=root/"evaluation_results/regression50_v314_20261007")
    parser.add_argument("--version",default="extraction-v3.14")
    args=parser.parse_args();base=args.baseline;out=args.output
    if out.exists():
        raise RuntimeError("Output already exists; preserve the existing run")
    manifest=json.loads((base/"benchmark_manifest.json").read_text())
    assert sum(e["sample_size"] for e in manifest["corpora"]) == 50
    rows=[]
    for entry in manifest["corpora"]:
        archive=Path(entry["sample_archive"])
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry["sample_archive_sha256"]
        selected=set(entry["documents"])
        observed={}
        for line in (base/"product"/f"corpus_{entry['pool_size']}"/"results.jsonl").read_text().splitlines():
            row=json.loads(line)
            if row.get("document") in selected and row.get("finished"):
                observed[row["document"]]=row
        assert set(observed) == selected
        rows.extend(observed.values())
    out.mkdir()
    previous_version=manifest["pipeline_version"]
    manifest.update(pipeline_version=args.version,previous_run=str(base),
        created_at=datetime.now(UTC).isoformat(),
        rerun_reason=f"User requested matched 50-case verification of {args.version}",
        native_runtime=".venv-ocr-candidate-v314",native_runtime_status="CANDIDATE_WITH_FOUR_REPORTED_OPENCV_DISTRIBUTION_NAME_CONFLICTS")
    for key in ["ground_truth_snapshot","verified_truth_snapshot"]:
        original=Path(manifest[key]);target=out/"verified_truth.json"
        if not target.exists():shutil.copy2(original,target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == manifest[key+"_sha256"]
        manifest[key]=str(target)
    (out/"benchmark_manifest.json").write_text(json.dumps(manifest,indent=2))
    (out/"baseline_results.json").write_text(json.dumps(rows,indent=2))
    shutil.copy2(base/"authorization.json",out/"authorization.json")
    driver=(base/"run_verification.py").read_text().replace(previous_version,args.version)
    driver=driver.replace("env['CDP_CROP_VLM_PROVIDER'] = 'claude'", "env['CDP_CROP_VLM_PROVIDER'] = 'claude'\n        env['CDP_LEARNED_MATCHER'] = '0'\n        env['HF_HUB_OFFLINE'] = '1'\n        env['TRANSFORMERS_OFFLINE'] = '1'\n        env['CDP_OCR_WORKER_POOL'] = '0'\n        env['CDP_OCR_TIMEOUT_SECONDS'] = '300'\n        env['CDP_COMPLETION_TIMEOUT_SECONDS'] = '120'\n        env['PYTHONPATH'] = str(ROOT) + __import__('os').pathsep + env.get('PYTHONPATH', '')")
    driver=driver.replace("DI and Claude only; label coverage remains partial.","DI and Claude only; label coverage remains partial. Single-OpenCV candidate runtime; upstream package-name conflicts are recorded in the manifest. No learned-matcher model downloads.")
    (out/"run_verification.py").write_text(driver)
    compile(driver,str(out/"run_verification.py"),"exec")
    (out/"verification_status.json").write_text(json.dumps({"status":"PREPARED","pipeline_version":args.version,
        "selected":50,"baseline_stp":sum(bool(r.get('true_stp')) for r in rows),"native_runtime":".venv-ocr-candidate-v314"},indent=2))
    print(json.dumps({"output":str(out),"selected":50,"baseline_finished":len(rows)}))


if __name__ == "__main__":
    main()
