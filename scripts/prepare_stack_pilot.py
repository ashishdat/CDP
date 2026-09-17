"""Freeze a 20-document development pilot; never execute or promote OCR routes.

The public report omits source filenames and field values. The private source
mapping is written only under the workspace's ignored evaluation_results tree.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, UnidentifiedImageError

COUNT = 20
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
STACK = {
    'registration': 'OpenCV/SIFT/FLANN/RANSAC',
    'primary_ocr': 'RapidOCR/ONNX',
    'selective_secondary_ocr': ['PaddleOCR', 'Tesseract'],
    'difficult_tables': 'Docling',
    'validation': 'Python/Pydantic',
    'ai_cascade': 'Azure',
    'cloud_ocr_fallback': 'AWS Textract DetectDocumentText',
    'field_review': 'React',
}


def sample_documents(archive: Path, seed: str, count: int = COUNT):
    """Sample by a seeded archive-entry ordering; never infer identity from names."""
    documents = []
    with ZipFile(archive) as source:
        entries = [entry for entry in source.infolist() if not entry.is_dir()]
        entries.sort(key=lambda entry: hashlib.sha256(
            (seed + '\0' + entry.filename).encode('utf-8')
        ).digest())
        seen = set()
        for entry in entries:
            if entry.file_size > MAX_DOCUMENT_BYTES:
                continue
            with source.open(entry) as stream:
                payload = stream.read(MAX_DOCUMENT_BYTES + 1)
            if len(payload) > MAX_DOCUMENT_BYTES:
                continue
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen:
                continue
            try:
                with Image.open(io.BytesIO(payload)) as image:
                    image.verify()
                with Image.open(io.BytesIO(payload)) as image:
                    dimensions = list(image.size)
                    pages = getattr(image, 'n_frames', 1)
                    image_format = image.format
            except (UnidentifiedImageError, OSError, ValueError):
                continue
            seen.add(digest)
            documents.append({
                'case_id': f'CASE-{len(documents) + 1:03d}',
                'sha256': digest, 'pages': pages, 'dimensions': dimensions,
                'format': image_format, 'private_archive_entry': entry.filename,
            })
            if len(documents) == count:
                return documents
    raise ValueError(f'Expected {count} distinct supported image documents; found {len(documents)}')


def readiness(code_root: Path, env_file: Path | None = None):
    # Explicit path only: never discover or copy credentials from other projects.
    settings = {}
    if env_file is not None:
        from dotenv import dotenv_values
        if not env_file.is_file():
            raise ValueError('Explicit environment file does not exist')
        settings.update(dotenv_values(env_file, interpolate=False))
    settings.update(os.environ)  # Process settings override file settings.

    packages = {name: importlib.util.find_spec(name) is not None for name in (
        'cv2', 'rapidocr_onnxruntime', 'onnxruntime', 'paddleocr', 'docling', 'pydantic',
    )}
    missing = [str(Path('templates') / family / name)
               for family in ('cms1500', 'ub04')
               for name in ('canonical.png', 'version.json', 'descriptors.npz',
                            'anchors.json', 'fields.json')
               if not (code_root / 'templates' / family / name).is_file()]
    azure = {name: bool(settings.get(name) and str(settings[name]).strip()) for name in (
        'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_AI_EVALUATION_DEPLOYMENT',
    )}
    blockers = ['PHASE2_REGISTRATION_GATE_NOT_PASSED',
                'RAPID_FIRST_RUNTIME_ROUTE_MIGRATION_NOT_VALIDATED']
    if missing:
        blockers.append('TEMPLATE_ASSETS_MISSING')
    if not packages['docling']:
        blockers.append('DOCLING_NOT_INSTALLED')
    if not all(azure.values()):
        blockers.append('AZURE_CONFIGURATION_INCOMPLETE')
    blockers.append('AWS_TRANSPORT_AND_AUTHENTICATION_NOT_VERIFIED')
    return {'packages_importable': packages, 'missing_template_assets': missing,
            'azure_environment_keys_present': azure,
            'azure_status': 'CONFIGURED_NOT_LIVE_VERIFIED' if all(azure.values()) else 'INCOMPLETE',
            'environment_file': str(env_file.resolve()) if env_file else None,
            'aws_status': 'NOT_VERIFIED_NO_NETWORK_REQUEST',
            'react_status': 'SOURCE_PRESENT_NOT_BROWSER_VALIDATED',
            'blockers': blockers,
            'note': 'Presence checks are not engine execution or asset integrity validation.'}


def prepare(archive: Path, code_root: Path, output: Path, workspace: Path, seed: str,
            env_file: Path | None = None):
    output = output.resolve()
    allowed = (workspace / 'evaluation_results').resolve()
    if not output.is_relative_to(allowed):
        raise ValueError('Pilot artifacts must stay under workspace/evaluation_results')
    if output.exists():
        raise ValueError('Output already exists; refusing to overwrite a frozen pilot')
    checked = subprocess.run(
        ['git', '-C', str(workspace), 'check-ignore', '--quiet', str(output / 'private_sources.json')],
        check=False, capture_output=True,
    )
    if checked.returncode != 0:
        raise ValueError('Artifact output must be ignored by Git')
    cases = sample_documents(archive, seed)
    checks = readiness(code_root, env_file) if env_file else readiness(code_root)
    sha = subprocess.check_output(
        ['git', '-C', str(code_root), 'rev-parse', 'HEAD'], text=True,
    ).strip()
    public = [{k: v for k, v in item.items() if k != 'private_archive_entry'} for item in cases]
    report = {
        'status': 'PREPARED_BLOCKED_NOT_EXECUTED',
        'created_at': datetime.now(UTC).isoformat(), 'code_sha': sha,
        'sample_kind': 'DEVELOPMENT_PILOT_NOT_INDEPENDENT_ACCURACY_HOLDOUT',
        'seed': seed, 'selected_documents': len(cases), 'processed_documents': 0,
        'sampling_policy': 'Seeded ordering; unique byte hashes; valid image containers <=50 MiB.',
        'ground_truth': 'UNAVAILABLE_NO_ACCURACY_CLAIM', 'stack': STACK,
        'readiness': checks, 'cases': public, 'cloud_calls': 0,
        'metrics': {'accuracy': None, 'true_stp': None, 'combined_hitl': None},
        'note': 'Blocked preparation is not a 20-document operational test or stack qualification.',
    }
    output.mkdir(parents=True)
    for name, value in (
        ('pilot_manifest.json', report),
        ('private_sources.json', {'archive': str(archive.resolve()), 'cases': cases}),
        ('case_status.json', [{'case_id': c['case_id'], 'status': 'BLOCKED_BEFORE_EXECUTION',
                               'reason_codes': checks['blockers']} for c in public]),
    ):
        (output / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--code-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', default='cdp-selected-stack-20-v1')
    parser.add_argument('--env-file', type=Path, help='Explicit dotenv settings; values are never reported')
    args = parser.parse_args()
    report = prepare(args.archive, args.code_root.resolve(), args.output,
                     Path(__file__).resolve().parents[1], args.seed, args.env_file)
    print(json.dumps({k: report[k] for k in
                      ('status', 'selected_documents', 'processed_documents', 'cloud_calls')}))
    return 2  # Fail closed: a prepared pilot is not a passed execution.


if __name__ == '__main__':
    raise SystemExit(main())
