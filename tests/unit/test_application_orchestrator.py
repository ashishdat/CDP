import json
import pytest
from application_orchestrator import ApplicationStateMachine, STAGES


def handlers(calls, stop=None, status='FAILED', error=None):
    def handler(name):
        def invoke(context):
            calls.append(name)
            if name == stop:
                if error:
                    raise error
                return {'status': status}
            return {'status': 'SUCCESS'}
        return invoke
    return {name: handler(name) for name in STAGES}


def test_order_and_serialization(tmp_path):
    calls = []
    machine = ApplicationStateMachine(handlers(calls))
    result = machine.run({}, tmp_path/'run')
    assert calls == list(STAGES) == result.completed_stages
    assert result.status == 'SUCCESS'
    assert result.failed_stage is None
    saved = json.loads((tmp_path/'run/ApplicationResult.json').read_text())
    assert [e['stage'] for e in saved['telemetry']] == list(STAGES)
    assert all(e['latency_ms'] >= 0 and e['timestamp'] for e in saved['telemetry'])
    with pytest.raises(RuntimeError):
        machine.run({}, tmp_path/'retry')
    assert calls == list(STAGES)


@pytest.mark.parametrize('stop', STAGES)
@pytest.mark.parametrize('status', ['FAILED', 'SKIPPED', 'UNAVAILABLE'])
def test_stop_after_every_non_success(tmp_path, stop, status):
    calls = []
    result = ApplicationStateMachine(handlers(calls, stop, status)).run({}, tmp_path/'run')
    index = STAGES.index(stop)
    assert calls == list(STAGES[:index+1])
    assert result.completed_stages == list(STAGES[:index])
    assert result.failed_stage == result.current_stage == stop
    assert result.status == status
    assert all(result.stages[s] == 'SKIPPED' for s in STAGES[index+1:])


@pytest.mark.parametrize('error,status', [(ValueError('bad contract'), 'FAILED'),
                                       (FileNotFoundError('asset missing'), 'UNAVAILABLE')])
def test_exception_is_persisted(tmp_path, error, status):
    calls = []
    result = ApplicationStateMachine(handlers(calls, 'geometry', error=error)).run({}, tmp_path/'run')
    assert result.failed_stage == 'geometry'
    assert result.status == status
    assert result.telemetry[-1]['error']['reason'] == str(error)
    assert 'ocr' not in calls


def test_invalid_status_fails_closed(tmp_path):
    calls = []
    result = ApplicationStateMachine(handlers(calls, 'classification', 'COMPLETED')).run({}, tmp_path/'run')
    assert result.status == 'FAILED'
    assert calls == ['classification']


def test_missing_handler_rejected():
    with pytest.raises(ValueError):
        ApplicationStateMachine({})
