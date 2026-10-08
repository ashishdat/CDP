"""Version the architecture description without changing frozen v1 assets."""
from pathlib import Path
import re
from packages.release_freeze import sha256_file


def main():
    root=Path.cwd()
    old=root/"config/architecture/redesign_stack_v1.yaml"
    new=root/"config/architecture/redesign_stack_v2.yaml"
    text=old.read_text(encoding="utf-8").replace("version: redesign-stack-v1","version: redesign-stack-v2")
    text=text.replace("capabilities:\n", "capabilities:\n  case_execution:\n    technology: [Python, owned process trees]\n    role: Bound OCR and completion independently; terminate only the timed-out claim process tree.\n    ocr_timeout_seconds: 300\n    completion_timeout_seconds: 120\n    shared_native_ocr_pool: false\n    status: CANDIDATE\n  local_crop_recovery:\n    technology: [OpenCV, printed cell frames]\n    role: Recheck all four cell edges before a coherent translation of at most six pixels; preserve actual crop coordinates.\n    acceptance_authority: EXISTING_FIELD_AND_CLAIM_GATES\n    status: CANDIDATE\n")
    text=text.replace("      default: off\n", "      default: on\n",1)
    new.write_text(text,encoding="utf-8")
    release=root/"config/releases/extraction-v3.yaml"
    text=release.read_text(encoding="utf-8").replace("config/architecture/redesign_stack_v1.yaml","config/architecture/redesign_stack_v2.yaml")
    text=re.sub(r"(?m)^(\s*config/architecture/redesign_stack_v2.yaml: )[a-f0-9]{64}$",lambda m:m[1]+sha256_file(new),text)
    text=text.replace("Generic TrOCR handwriting output is non-authoritative; gpt-4o crop is the preferred", "Generic TrOCR handwriting output is non-authoritative; Claude crop is the preferred")
    text=text.replace("Azure DI charge residual and PP-OCRv5 Server are off by default (not on recommended\n  stack).", "Azure DI charge residual is enabled for authorized PRODUCT recovery; PP-OCRv5 Server remains disabled.")
    release.write_text(text,encoding="utf-8")


if __name__ == "__main__":
    main()
