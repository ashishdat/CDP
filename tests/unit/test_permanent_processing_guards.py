from PIL import Image
import pytest

def test_member_suffix_and_observed_zero_are_preserved():
    from packages.extraction_recovery.span_selection import select_field_span
    for raw in ['OSC75126744-01','0SC74765420','OSC75126744','G18-0001006']:
        assert select_field_span(raw,'ALPHANUMERIC_ID','insured_id_number').selected_text==raw

def test_expired_shared_budget_does_not_start_matching(monkeypatch):
    from packages.recovery import registration_deadline as budget
    from workers.page_detection import template_alignment as alignment
    clock=iter([0,131]);monkeypatch.setattr(budget,'monotonic',lambda:next(clock))
    monkeypatch.setattr(alignment,'_gray',lambda *args:pytest.fail('Expired budget must stop before image work'))
    @budget.bounded_registration
    def process():return alignment.align_to_reference(Image.new('L',(64,64)),Image.new('L',(64,64)))
    result=process()
    assert not result.accepted and result.evidence.rejection_reason=='REGISTRATION_RECOVERY_BUDGET_EXHAUSTED'
    assert budget._deadline.get() is None

def test_shared_budget_resets_on_exception(monkeypatch):
    from packages.recovery import registration_deadline as budget
    @budget.bounded_registration
    def broken():raise RuntimeError('test')
    with pytest.raises(RuntimeError):broken()
    assert budget._deadline.get() is None
