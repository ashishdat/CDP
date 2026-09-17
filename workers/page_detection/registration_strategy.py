"""Registration gates; matching, estimation and safety policies remain owned by runtime."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

ACTIVE_MACHINE = ContextVar('registration_state_machine', default=None)


class RegistrationState(StrEnum):
    ASSET_CHECK = 'ASSET_CHECK'
    LINEAGE_CHECK = 'LINEAGE_CHECK'
    CORRESPONDENCE_CHECK = 'CORRESPONDENCE_CHECK'
    HOMOGRAPHY = 'HOMOGRAPHY'
    SAFETY = 'SAFETY'
    SUCCESS = 'SUCCESS'


FAILURES = dict(zip(list(RegistrationState)[:-1],
                    ['AssetFailure', 'LineageFailure', 'CorrespondenceFailure',
                     'HomographyFailure', 'SafetyFailure']))


@dataclass
class RegistrationStateMachine:
    state: RegistrationState = RegistrationState.ASSET_CHECK
    failure_reason: str | None = None
    evidence: list = field(default_factory=list)

    def enter(self, state, **evidence):
        if self.failure_reason:
            raise RuntimeError('Registration gate already failed')
        self.state = RegistrationState(state)
        self.record('STARTED', **evidence)

    def record(self, status, **evidence):
        from workers.page_detection.registration_telemetry import ACTIVE
        item = {'registration_state': self.state.value, 'status': status, **evidence}
        self.evidence.append(item)
        trace = ACTIVE.get()
        if trace is not None:
            trace.emit(self.state.value, status, **evidence)

    def fail(self, reason):
        if not self.failure_reason:
            self.failure_reason = FAILURES[self.state]
            self.record(self.failure_reason, reason=reason)

    def snapshot(self):
        return {'RegistrationState': self.state.value, 'FailureReason': self.failure_reason,
                'Evidence': list(self.evidence)}


def enter(state, **evidence):
    machine = ACTIVE_MACHINE.get()
    if machine is not None:
        machine.enter(state, **evidence)


def correspondence_evidence(source, template):
    """Necessary geometric identifiability; no matching, deduplication or fitting."""
    result = {}
    for name, points in [('image', source), ('template', template)]:
        points = np.asarray(points).reshape(-1, 2)
        finite = bool(np.isfinite(points).all())
        unique = np.unique(points, axis=0) if finite else np.empty((0, 2))
        rank = int(np.linalg.matrix_rank(unique - unique.mean(axis=0))) if len(unique) else 0
        result[name] = {'finite': finite, 'unique_coordinates': len(unique), 'affine_rank': rank}
    result['valid'] = all(v['finite'] and v['unique_coordinates'] >= 4 and v['affine_rank'] == 2
                          for k, v in result.items() if k != 'valid')
    return result
