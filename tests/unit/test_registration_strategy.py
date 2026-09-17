import json
import numpy as np
import pytest
from PIL import Image
from unittest.mock import Mock
from workers.page_detection.registration_strategy import correspondence_evidence, RegistrationStateMachine
from workers.page_detection.template_alignment import align_to_reference

@pytest.mark.parametrize('points,valid', [
    ([[0,0]]*31, False),
    ([[0,0],[1,0],[0,1],[0,1]], False),
    ([[0,0],[1,1],[2,2],[3,3]], False),
    ([[0,0],[1,0],[0,1],[1,1]], True),
])
def test_geometric_gate(points, valid):
    assert correspondence_evidence(points, points)['valid'] is valid


def test_missing_asset_stops_before_lineage(monkeypatch):
    import workers.page_detection.template_alignment as module
    forbidden=Mock(side_effect=AssertionError('Must stop at asset check'))
    monkeypatch.setattr(module, 'assess_template_compatibility', forbidden)
    result=align_to_reference(None,None)
    assert result.registration_state['FailureReason']=='AssetFailure'
    forbidden.assert_not_called()
    json.dumps(result.registration_state)


def test_lineage_stops_before_engines(monkeypatch):
    from types import SimpleNamespace
    import workers.page_detection.template_alignment as module
    monkeypatch.setattr(module, 'assess_template_compatibility', lambda *a,**k: SimpleNamespace(status='INCOMPATIBLE'))
    forbidden=Mock(side_effect=AssertionError('Engine must not execute'))
    monkeypatch.setattr(module,'_cheap_alignment',forbidden)
    with Image.new('L',(20,20)) as image:
        result=align_to_reference(image,image)
    assert result.registration_state['FailureReason']=='LineageFailure'
    forbidden.assert_not_called()


def test_failed_machine_cannot_continue():
    machine=RegistrationStateMachine()
    machine.fail('missing')
    with pytest.raises(RuntimeError): machine.enter('HOMOGRAPHY')

def test_degenerate_correspondences_never_call_homography(monkeypatch):
    import cv2
    from types import SimpleNamespace
    import workers.page_detection.template_alignment as module
    from workers.page_detection.registration_strategy import ACTIVE_MACHINE
    points=[cv2.KeyPoint(float(i), float(i), 1) for i in range(12)]
    sift=SimpleNamespace(detect=lambda *a: points, detectAndCompute=lambda *a: (points,np.ones((12,128),np.float32)))
    monkeypatch.setattr(module.cv2,'SIFT_create',lambda **k:sift)
    pairs=[[cv2.DMatch(i,i,1),cv2.DMatch(i,(i+1)%12,10)] for i in range(12)]
    monkeypatch.setattr(module.cv2,'FlannBasedMatcher',lambda *a:SimpleNamespace(knnMatch=lambda *a,**k:pairs))
    forbidden=Mock(side_effect=AssertionError('Homography must not execute'))
    monkeypatch.setattr(module.cv2,'findHomography',forbidden)
    machine=RegistrationStateMachine();token=ACTIVE_MACHINE.set(machine)
    try:
        result=module._sift_alignment(np.full((100,100),255,np.uint8),np.full((100,100),255,np.uint8),module.DEFAULT_REGISTRATION_POLICY)
        assert result.evidence.rejection_reason=='degenerate_correspondences'
        assert machine.state=='CORRESPONDENCE_CHECK'
        forbidden.assert_not_called()
    finally:
        ACTIVE_MACHINE.reset(token)
