"""Check installed local UAT extraction dependencies without network or secrets."""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from packages.runtime_profile.contracts import ROOT, RuntimeDecisionProfile
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance


def inspect():
    checks = {}
    for package, module in [('Pillow', 'PIL'), ('PyMuPDF', 'pymupdf'),
                            ('opencv-python-headless', 'cv2'), ('pydantic', 'pydantic'), ('PyYAML', 'yaml')]:
        available = importlib.util.find_spec(module) is not None
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = None
        checks[module] = {'available': available, 'version': version}
    executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract') or r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    present = Path(executable).is_file()
    checks['tesseract'] = {'available': present, 'path': executable}
    if present:
        result = subprocess.run([executable, '--version'], capture_output=True, text=True, check=True, timeout=10)
        checks['tesseract']['version'] = result.stdout.splitlines()[0]
        languages = subprocess.run([executable, '--list-langs'], capture_output=True,
                                  text=True, check=True, timeout=10)
        checks['tesseract']['english_model_available'] = 'eng' in languages.stdout.splitlines()
        checks['tesseract']['available'] = checks['tesseract']['english_model_available']
    profile = RuntimeDecisionProfile.load(ROOT/'config/runtime_profiles/uat_evaluation_v1.yaml')
    config = ExtractionAcceptance().config
    return {'python': sys.executable, 'python_version': sys.version.split()[0],
        'local_extraction_ready': all(check['available'] for check in checks.values()),
        'checks': checks, 'profile_hashes_valid': True, 'profile': profile.decision_identity(),
        'acceptance_policy': config,
        'execution': {'engine': 'tesseract', 'dpi': 200, 'mode': 'evaluation',
            'required_services': [], 'required_api_keys': [], 'cloud_calls_required': False},
        'optional_secondary_ocr_installed': importlib.util.find_spec('rapidocr_onnxruntime') is not None,
        'limitations': ['OCR confidence is not measured accuracy.',
            'Identity, photo matching, geolocation authenticity and medical/underwriting verification are outside extraction scope.',
            'Unreadable or incomplete structured fields still require review.',
            'Photo-only completion means all page image assets are persisted, not visual identity verification.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inspect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['local_extraction_ready'] else 1)
