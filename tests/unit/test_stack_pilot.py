import io
from zipfile import ZipFile

import pytest
from PIL import Image

from scripts.prepare_stack_pilot import prepare, sample_documents


def make_archive(path):
    with ZipFile(path, 'w') as archive:
        for index in range(25):
            image = Image.new('RGB', (32, 32), (index, 0, 0))
            data = io.BytesIO()
            image.save(data, format='TIFF')
            # Deliberately no image suffix; the real archive uses numeric suffixes.
            archive.writestr(f'private-document.{index:03}', data.getvalue())
        archive.writestr('not-an-image.txt', b'not a claim')
    return path


def test_sample_is_reproducible_and_has_twenty_distinct_documents(tmp_path):
    archive = make_archive(tmp_path / 'claims.zip')
    first = sample_documents(archive, 'seed')
    assert first == sample_documents(archive, 'seed')
    assert len(first) == len({row['sha256'] for row in first}) == 20
    assert all(row['format'] == 'TIFF' for row in first)
    assert [row['case_id'] for row in first] == [f'CASE-{n:03}' for n in range(1, 21)]


def test_insufficient_documents_fails_instead_of_reducing_denominator(tmp_path):
    archive = make_archive(tmp_path / 'claims.zip')
    with pytest.raises(ValueError, match='Expected 30'):
        sample_documents(archive, 'seed', count=30)


def test_output_cannot_escape_private_artifact_root(tmp_path):
    with pytest.raises(ValueError, match='must stay under'):
        prepare(tmp_path / 'unused.zip', tmp_path, tmp_path / 'public', tmp_path, 'seed')


def test_public_manifest_contains_no_archive_names_or_false_success(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from scripts import prepare_stack_pilot as pilot

    archive = make_archive(tmp_path / 'claims.zip')
    monkeypatch.setattr(pilot.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(pilot.subprocess, 'check_output', lambda *a, **k: 'test-sha\n')
    monkeypatch.setattr(pilot, 'readiness', lambda root: {'blockers': ['TEST_BLOCKER']})
    output = tmp_path / 'evaluation_results' / 'pilot'
    report = prepare(archive, tmp_path, output, tmp_path, 'seed')
    public_text = (output / 'pilot_manifest.json').read_text(encoding='utf-8')
    assert 'private-document' not in public_text
    assert report['selected_documents'] == 20
    assert report['processed_documents'] == report['cloud_calls'] == 0
    assert all(value is None for value in report['metrics'].values())
    statuses = json.loads((output / 'case_status.json').read_text(encoding='utf-8'))
    assert len(statuses) == 20
    assert all(row['status'] == 'BLOCKED_BEFORE_EXECUTION' for row in statuses)
    with pytest.raises(ValueError, match='refusing to overwrite'):
        prepare(archive, tmp_path, output, tmp_path, 'seed')


def test_explicit_dotenv_detects_azure_without_exposing_values(tmp_path, monkeypatch):
    import json

    from scripts.prepare_stack_pilot import readiness

    keys = ['AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_AI_EVALUATION_DEPLOYMENT']
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / '.env'
    env.write_text('\n'.join(f'{key}=private-test-value' for key in keys), encoding='utf-8')
    result = readiness(tmp_path, env)
    assert result['azure_status'] == 'CONFIGURED_NOT_LIVE_VERIFIED'
    assert 'AZURE_CONFIGURATION_INCOMPLETE' not in result['blockers']
    assert 'private-test-value' not in json.dumps(result)
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', '')
    assert readiness(tmp_path, env)['azure_status'] == 'INCOMPLETE'
    with pytest.raises(ValueError, match='does not exist'):
        readiness(tmp_path, tmp_path / 'missing.env')
