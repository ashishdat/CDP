import os,json,subprocess
from pathlib import Path
from scripts import benchmark_hackathon_four_corpora as benchmark

root=Path.cwd();out=root/"evaluation_results/v315_charge_retest";out.mkdir(exist_ok=True);benchmark.OUT=out
manifest=json.loads((root/"evaluation_results/regression50_v314_20261007/benchmark_manifest.json").read_text())
env=benchmark.run_env(out,manifest["corpora"][0]["sample_archive"],"PRODUCT")
env["CDP_CROP_VLM_PROVIDER"]="claude"
for key in list(env):
    if key.startswith("AZURE_OPENAI_") or key.startswith("OPENAI_"):env.pop(key)
env["PYTHONPATH"]=str(root)+os.pathsep+env.get("PYTHONPATH","")
with (out/"native.log").open("w",encoding="utf-8") as log:
    result=subprocess.run([str(root.parent.parent/".venv-ocr-candidate-v314/Scripts/python.exe"),"-m","scripts.retest_v315_charge_sources"],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
print("Charge source retest exit",result.returncode)
