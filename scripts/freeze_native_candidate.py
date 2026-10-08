"""Freeze installed native dependencies with one explicit cv2 provider."""
import importlib.metadata as metadata
import json
from pathlib import Path

PROVIDERS={"opencv-python","opencv-python-headless","opencv-contrib-python","opencv-contrib-python-headless"}


def main():
    root=Path.cwd();out=root/"evaluation_results/architecture_v314";out.mkdir(exist_ok=True)
    installed={d.metadata["Name"].lower().replace("_","-"):d.version for d in metadata.distributions()}
    provider="opencv-contrib-python"
    if provider not in installed:
        raise RuntimeError("Qualified installed OpenCV contrib provider missing")
    pins={name:version for name,version in installed.items()
          if name not in {"idp-claims-platform", "lightglue"} and (name not in PROVIDERS or name == provider)}
    (out/"native_candidate.lock.txt").write_text("\n".join(f"{name}=={version}" for name,version in sorted(pins.items()))+"\n")
    dependencies=[]
    for dist in metadata.distributions():
        required=[r for r in dist.requires or [] if any(p in r.lower() for p in PROVIDERS)]
        if required:
            dependencies.append({"package":dist.metadata["Name"],"requirements":required})
    (out/"native_candidate_profile.json").write_text(json.dumps({
        "opencv_provider":provider,"pins":pins,"upstream_opencv_requirements":dependencies,
        "excluded_optional_features":["lightglue learned matching; keep CDP_LEARNED_MATCHER=0"],
        "qualification":"Candidate only. Some upstream distribution-name requirements expect different OpenCV wheels although those wheels share cv2. Preserve metadata, report these exceptions, and require native compatibility checks before adoption."},indent=2))
    print(json.dumps({"pinned_packages":len(pins),"opencv_provider":provider}))


if __name__ == "__main__":
    main()
