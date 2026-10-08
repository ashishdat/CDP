import pytest
import sys
from types import SimpleNamespace
from PIL import Image

from packages.extraction_recovery.field_cascade import field_requires_independent_confirmation
from packages.templates.identity import template_fingerprint
from packages.templates.registry import TemplateRegistry
from scripts.ocr_from_geometry import _attach_local_dob_confirmation, _dob_cell_bboxes, _dob_reads_confirmed, _load_cms1500_template


def test_ocr_uses_active_release_instead_of_first_registered_template(monkeypatch):
    monkeypatch.delenv('CDP_RELEASE_MANIFEST', raising=False)
    monkeypatch.setenv('CDP_PIPELINE_RELEASE', 'extraction-v3')
    assert _load_cms1500_template().version == '03'


def test_saved_template_binding_overrides_current_release(monkeypatch):
    monkeypatch.setenv('CDP_PIPELINE_RELEASE', 'extraction-v2')
    template = TemplateRegistry.load_from_directory().get('cms1500', '03')
    record = {'template_id': 'cms1500', 'template_version': '03',
              'template_fingerprint': template_fingerprint(template)}
    assert _load_cms1500_template(record, record).version == '03'


def test_template_mismatch_and_changed_definition_are_rejected():
    record = {'template_id': 'cms1500', 'template_version': '03'}
    with pytest.raises(ValueError, match='disagree'):
        _load_cms1500_template(record, {'template_id': 'cms1500', 'template_version': '02-12'})
    with pytest.raises(ValueError, match='definition changed'):
        _load_cms1500_template({**record, 'template_fingerprint': 'different'})


def test_dob_day_crop_contains_both_digits_and_does_not_share_year_pixels():
    cells = _dob_cell_bboxes((674, 425, 882, 456))
    # Observed day-19 glyph envelope in the reference-aligned failing sample.
    assert cells['DD'][0] <= 755 and cells['DD'][2] >= 781
    assert cells['MM'][2] < cells['DD'][0]
    assert cells['DD'][2] < cells['YY'][0]


def test_a_date_shape_requires_actual_confirmation():
    assert field_requires_independent_confirmation('patient_dob')
    one = {'value': '03/19/1943', 'engine': 'rapidocr'}
    assert not _dob_reads_confirmed([one])
    assert not _dob_reads_confirmed([one, {**one, 'engine': ''}])
    assert not _dob_reads_confirmed([one, {**one, 'value': '03/19/1948', 'engine': 'paddleocr'}])
    assert _dob_reads_confirmed([one, {**one, 'engine': 'paddleocr'}])


def test_compact_dob_is_selected_without_guessing_from_caption_digits():
    from packages.extraction_recovery.span_selection import select_field_span

    result = select_field_span('MM1DD YY 09021998 M', 'DATE', 'patient_dob')
    assert result.selected_text == '09/02/1998'
    assert result.candidate_spans == ('09021998',)
    ambiguous = select_field_span('09021998 09121998', 'DATE', 'patient_dob')
    assert ambiguous.selected_text == ''


def test_local_dob_confirmation_preserves_the_original_reader(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: '09021998'))
    original = {'candidates': [{'engine': 'paddleocr', 'value': '09/02/1998'}], 'attempts': []}
    repaired = _attach_local_dob_confirmation(original, Image.new('L', (1712, 2214), 255),
                                              (672, 420, 883, 457))
    assert len(original['candidates']) == 1
    assert repaired['candidates'][-1]['engine'] == 'tesseract'
    assert repaired['candidates'][-1]['raw_value'] == '09021998'
    assert _dob_reads_confirmed(repaired['candidates'])


def test_local_dob_confirmation_does_not_hide_disagreement(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: '09121998'))
    original = {'candidates': [{'engine': 'paddleocr', 'value': '09/02/1998'}], 'attempts': []}
    repaired = _attach_local_dob_confirmation(original, Image.new('L', (1712, 2214), 255),
                                              (672, 420, 883, 457))
    assert repaired['candidates'][0]['value'] == '09/02/1998'
    assert not _dob_reads_confirmed(repaired['candidates'])


def test_local_confirmation_keeps_acquiring_when_components_contradict(monkeypatch):
    import scripts.ocr_from_geometry as ocr

    calls = []
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: calls.append('band') or '09021998'))
    monkeypatch.setattr(ocr, '_recognize_dob_cells_for_engine',
        lambda *args: (calls.append('cells') or [], [], 'DOB_CELL_PARTIAL_DIGIT'))
    original = {'candidates': [{'engine': engine, 'value': '09/02/1998'}
                               for engine in ('paddleocr', 'rapidocr')],
                'attempts': [{'engine': 'tesseract',
                              'observation': {'parts': {'DD': '12'}}}]}
    repaired = _attach_local_dob_confirmation(original, Image.new('L', (1712, 2214), 255),
                                              (672, 420, 883, 457))
    assert calls == ['band', 'band', 'cells']
    assert not _dob_reads_confirmed(repaired['candidates'], repaired['attempts'])
    assert repaired['attempts'][0] == original['attempts'][0]


@pytest.mark.parametrize('text', [
    '09/02/1998 09/12/1998', '1998-09-02 09/12/1998',
    '09021998 09/12/1998',
])
def test_dob_multiple_intact_dates_require_recovery(text):
    from packages.extraction_recovery.span_selection import select_field_span

    result = select_field_span(text, 'DATE', 'patient_dob')
    assert result.selected_text == ''
    assert 'MULTIPLE_VALID_DATES_REQUIRES_REVIEW' in result.reason_codes


def test_dob_equivalent_intact_dates_preserve_iso_component_order():
    from packages.extraction_recovery.span_selection import select_field_span

    assert select_field_span('1998-09-02 09/02/1998', 'DATE', 'patient_dob').selected_text == '09/02/1998'


def test_dob_uses_recorded_word_positions_not_detector_order():
    from scripts.ocr_from_geometry import _field_observation_text
    from packages.extraction_recovery.span_selection import select_field_span

    lines = [SimpleNamespace(text='110', x0=735, y0=435),
             SimpleNamespace(text='1974.', x0=791, y0=435),
             SimpleNamespace(text='02', x0=691, y0=438)]
    raw = _field_observation_text(SimpleNamespace(lines=lines), 'patient_dob')
    assert raw == '02\n110\n1974.'
    assert select_field_span(raw, 'DATE', 'patient_dob').selected_text == '02/10/1974'


def test_date_shape_does_not_disable_handwriting_confirmation(monkeypatch):
    from packages.extraction_recovery import dob_trocr_residual as residual

    called = []
    def record(**kwargs):
        called.append(kwargs['local_accepted'])
        return residual.DobTrOCRResidualResult(attempted=False, configured=False,
            review_only=False, value=None, raw_value=None, date_shaped=False, reason='TEST')
    monkeypatch.setattr(residual, 'run_dob_trocr_residual', record)
    row = {'field': 'patient_dob', 'ocr_region': [0, 0, 100, 30],
           'cascade': {'accepted': True},
           'candidates': [{'engine': 'paddleocr', 'value': '03/19/1943'}]}
    residual.maybe_attach_dob_trocr_to_field_row(row, image=Image.new('L', (100, 30)),
                                              gap_class='AMBIGUOUS_DIGIT_FRAGMENTS')
    assert called == [False]


def test_charge_digit_fill_retains_actual_reader_family(monkeypatch):
    from packages.ocr.independence import independence_group
    from scripts.ocr_from_geometry import _recognize_charge_digits_only

    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: '250.00'))
    candidates, attempts, _ = _recognize_charge_digits_only(
        Image.new('L', (200, 80), 255), (10, 10, 180, 70))
    assert candidates
    assert all(candidate['engine'] == 'tesseract_digits' for candidate in candidates)
    assert all(independence_group(candidate['engine']) == 'TESSERACT_FAMILY'
               for candidate in candidates)
    assert all(attempt['engine'] == 'tesseract_digits' for attempt in attempts)


def test_critical_total_and_identity_acquire_confirmation():
    for field in ('total_charge', 'insured_id_number', 'insured_name'):
        assert field_requires_independent_confirmation(field)


def test_observed_explicit_currency_digits_are_not_dropped():
    from packages.ocr_portfolio import shape_monetary

    for amount in ('2701.00', '6404.00', '2605.00', '105.00', '10000.00'):
        assert shape_monetary(amount) == amount
    assert shape_monetary('$2,701.00') == '2701.00'


def test_aliases_of_same_reader_cannot_complete_acquisition():
    from packages.extraction_recovery.field_cascade import pick_engine_candidates

    candidates = [{'engine': engine, 'value': '03/19/1943'}
                  for engine in ('rapidocr', 'rapidocr-onnx')]
    _, _, reason, _ = pick_engine_candidates('patient_dob', candidates, 'date')
    assert not reason.startswith('MULTI_ENGINE_AGREEMENT:')


def test_mixed_reader_fragments_are_never_fused_into_a_reader_observation():
    from packages.extraction_recovery.field_cascade import FieldCascade

    def recognize(field, bbox, field_type, engines):
        return [{'engine': 'paddleocr', 'value': '6 4 1 g 7'},
                {'engine': 'rapidocr', 'value': 'ign i 1974'}], [], 'OBSERVED'
    result = FieldCascade().recognize(field_name='patient_dob',
        primary_bbox=(672, 424, 871, 457),
        cell={'x0': 667, 'y0': 402, 'x1': 886, 'y1': 459},
        image_size=(1700, 2200), recognize_fn=recognize)
    assert not result.accepted
    assert not any(s.variant_id == 'cross_variant_span' for s in result.cascade_trace)


def test_exhausted_critical_cascade_retains_later_reader_observations():
    from packages.extraction_recovery.field_cascade import FieldCascade

    values = iter(('05/18/1975', '05/18/1987'))
    def recognize(field, bbox, field_type, engines):
        if engines == ('tesseract',):
            return [], [{'engine': 'tesseract', 'reason': 'EMPTY'}], 'EMPTY'
        value = next(values, '05/18/1987')
        return [{'engine': 'rapidocr', 'value': value, 'raw_value': value}], [], 'OBSERVED'
    result = FieldCascade().recognize(field_name='patient_dob',
        primary_bbox=(672, 424, 871, 457),
        cell={'x0': 667, 'y0': 402, 'x1': 886, 'y1': 459},
        image_size=(1700, 2200), recognize_fn=recognize)
    assert {'05/18/1975', '05/18/1987'} <= {c['value'] for c in result.candidates}


def test_dob_parser_cannot_drop_arbitrary_observed_edge_digits():
    from packages.extraction_recovery.span_selection import select_field_span

    assert select_field_span('0511875', 'DATE', 'patient_dob').selected_text != '05/11/1987'
    assert select_field_span('0319983', 'DATE', 'patient_dob').selected_text == '03/19/1983'


def test_partial_numeric_fragment_is_not_normalized_as_a_complete_date():
    from packages.field_normalization import normalize_date

    assert normalize_date('8175') == (None, False)
    assert normalize_date('081975') == ('1975-08-19', True)
    assert normalize_date('8/1/75') == ('1975-08-01', True)


def test_invalid_two_digit_month_does_not_stop_the_next_reader_setting(monkeypatch):
    from scripts import ocr_from_geometry as ocr

    reads = iter(('60', '09', '21', '1965'))
    monkeypatch.setattr(ocr, '_digit_psms_dob', lambda: (8, 7))
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: next(reads)))
    candidates, attempts, _ = ocr._recognize_dob_cells_for_engine(
        Image.new('L', (1712, 2214), 255), (674, 425, 882, 456), None, ('tesseract',))
    assert candidates[0]['value'] == '09/21/1965'
    assert [a['reason'] for a in attempts if a.get('dob_cell') == 'MM'] == ['PSM_8', 'PSM_7']


def test_partial_month_and_year_cannot_supply_a_missing_day():
    from packages.extraction_recovery.span_selection import select_field_span

    assert select_field_span('09 1965 n', 'DATE', 'patient_dob').selected_text != '09/19/1965'
    assert select_field_span('09 11965', 'DATE', 'patient_dob').selected_text != '09/11/1965'
    assert select_field_span('09 11 1965', 'DATE', 'patient_dob').selected_text == '09/11/1965'


def test_partial_reader_year_contradiction_blocks_cell_agreement():
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts, dob_reads_confirmed

    candidates = [{'engine': engine, 'value': '05/15/2010'}
                  for engine in ('paddleocr', 'tesseract')]
    attempts = [{'engine': 'rapidocr', 'reason': 'DOB_CELL_COMPONENTS',
                 'observation': {'parts': {'MM': '', 'DD': '15', 'YY': '19'}}}]
    assert dob_component_conflicts(candidates, attempts) == [
        {'engine': 'rapidocr', 'component': 'YY', 'observed': '19'}]
    assert not dob_reads_confirmed(candidates, attempts)
    attempts[0]['observation']['parts']['YY'] = '10'
    assert dob_reads_confirmed(candidates, attempts)


def test_source_component_conflict_cannot_be_auto_accepted():
    from packages.criticality import CriticalityLevel
    from packages.evidence_decision.contracts import DecisionContext, FieldDisposition
    from packages.runtime_profile.decision_factory import DecisionServiceFactory

    decision = DecisionServiceFactory.from_profile().evidence_decision.decide(DecisionContext(
        field_name='patient_dob', document_family='CMS1500', criticality=CriticalityLevel.C3,
        deterministic_evidence={'DOB_COMPONENT_CONFLICT', 'DATE_VALID'},
        hard_validation_passed=True, registration_confidence=0.99))
    assert decision.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert 'DOB_COMPONENT_CONFLICT' in decision.reason_codes


def test_dob_crop_covers_the_observed_descender_without_changing_v2():
    registry = TemplateRegistry.load_from_directory()
    assert registry.get('cms1500', '03').field_region('patient_dob').y1 >= 465


def test_year_only_band_cannot_be_relabelled_as_three_dob_cells():
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine

    candidates, attempts, reason = _recognize_dob_cells_for_engine(
        Image.new('L', (1712, 2214), 255), (766, 435, 882, 464), None, ('tesseract',))
    assert candidates == []
    assert reason == 'DOB_PARTIAL_BAND_NOT_THREE_CELLS'


def test_complete_date_rivals_stay_in_normal_conflict_policy():
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts

    candidates = [{'engine': 'paddleocr', 'value': '05/18/1975'}]
    attempts = [{'engine': 'tesseract', 'observation': {
        'parts': {'MM': '05', 'DD': '13', 'YY': '75'}}}]
    assert dob_component_conflicts(candidates, attempts) == [{'engine': 'tesseract', 'component': 'DD', 'observed': '13'}]


def test_later_complete_reader_retains_its_earlier_partial_contradiction():
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts

    candidates = [{'engine': 'paddleocr', 'value': '05/18/1975'}]
    attempts = [{'engine': 'tesseract', 'observation': {'parts': {'DD': '13'}}},
                {'engine': 'tesseract', 'observation': {
                    'parts': {'MM': '05', 'DD': '18', 'YY': '75'}}}]
    assert dob_component_conflicts(candidates, attempts) == [{'engine': 'tesseract', 'component': 'DD', 'observed': '13'}]


def test_padded_dob_crop_stops_at_observed_border_inside_safe_region():
    from PIL import ImageDraw
    from scripts.ocr_from_geometry import _dob_bbox_before_bottom_ruling

    for border in (459, 464):
        image = Image.new('L', (1712, 2214), 255)
        ImageDraw.Draw(image).line((672, border, 882, border), fill=0)
        assert _dob_bbox_before_bottom_ruling(image, (672, 420, 883, 465)) == (672, 420, 883, border)
    assert _dob_bbox_before_bottom_ruling(Image.new('L', (1712, 2214), 255),
                                         (672, 420, 883, 465)) == (672, 420, 883, 465)


def test_cell_year_uses_physical_glyph_order_instead_of_detector_order():
    from dataclasses import dataclass
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine

    @dataclass
    class Line:
        text: str
        x0: int
        y0: int = 0
    @dataclass
    class Observation:
        lines: list
    readings = iter(([Line('05', 0)], [Line('18', 0)], [Line('5', 20), Line('7', 0)]))
    router = SimpleNamespace(route=lambda request: SimpleNamespace(attempts=[SimpleNamespace(
        engine='rapidocr', reason='OBSERVED', latency_ns=0,
        observation=Observation(next(readings)))]))
    candidates, attempts, _ = _recognize_dob_cells_for_engine(
        Image.new('L', (1712, 2214), 255), (674, 435, 882, 458), router, ('rapidocr',))
    assert candidates[0]['value'] == '05/18/1975'
    assert attempts[-1]['observation']['parts']['YY'] == '75'


def test_cell_caption_digit_does_not_destroy_complete_numeric_observation():
    from dataclasses import dataclass
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts

    @dataclass
    class Line:
        text: str
        x0: int
        y0: int = 0
    @dataclass
    class Observation:
        lines: list
    # Reproduces M048EJG7.017: label noise was concatenated with month 12.
    readings = iter(([Line('mma1', 74), Line('12', 82)], [Line('18', 12)],
                     [Line('199', 0), Line('7', 114), Line('B', 224)]))
    router = SimpleNamespace(route=lambda request: SimpleNamespace(attempts=[SimpleNamespace(
        engine='rapidocr', reason='OBSERVED', latency_ns=0,
        observation=Observation(next(readings)))]))
    candidates, attempts, _ = _recognize_dob_cells_for_engine(
        Image.new('L', (1712, 2214), 255), (674, 428, 882, 459), router, ('rapidocr',))
    assert candidates[0]['value'] == '12/18/1997'
    assert attempts[-1]['observation']['parts']['MM'] == '12'
    earlier = {'engine': 'rapidocr', 'observation': {'parts': {'YY': '99'}}}
    assert dob_component_conflicts(candidates, [earlier, *attempts]) == [{'engine': 'rapidocr', 'component': 'YY', 'observed': '99'}]


def test_alphanumeric_cell_noise_cannot_create_observed_digits():
    from dataclasses import dataclass
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine

    @dataclass
    class Line:
        text: str
        x0: int = 0
        y0: int = 0
    @dataclass
    class Observation:
        lines: list
    readings = iter(('m1m2', '18', '1997'))
    router = SimpleNamespace(route=lambda request: SimpleNamespace(attempts=[SimpleNamespace(
        engine='rapidocr', reason='OBSERVED', latency_ns=0,
        observation=Observation([Line(next(readings))]))]))
    candidates, attempts, _ = _recognize_dob_cells_for_engine(
        Image.new('L', (1712, 2214), 255), (674, 428, 882, 459), router, ('rapidocr',))
    assert candidates == []
    assert attempts[-1]['observation']['parts']['MM'] == ''
