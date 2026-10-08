import sys
from types import SimpleNamespace

import pytest

from workers.cascade.azure_read_adapter import spatial_dob_components


def word(text, x, y):
    return {'content': text, 'polygon': [x, y, x + 16, y, x + 16, y + 12, x, y + 12]}


def observed_words():
    return (word('2010', 140, 40), word('DD', 80, 10), word('01', 20, 40),
            word('YY', 140, 10), word('15', 80, 40), word('MM', 20, 10))


def test_dob_uses_physical_cell_positions_instead_of_provider_content_order():
    assert spatial_dob_components(observed_words()) == '01/15/2010'


def test_dob_does_not_choose_between_two_observed_days_or_join_other_lines():
    assert spatial_dob_components(observed_words() + (word('13', 80, 40),)) is None
    words = tuple(w for w in observed_words() if w['content'] != '2010')
    assert spatial_dob_components(words + (word('2010', 140, 90),)) is None


def test_missing_headers_or_year_digits_do_not_mint_a_date():
    assert spatial_dob_components(tuple(w for w in observed_words() if w['content'] != 'MM')) == '01/15/2010'
    words = tuple(w for w in observed_words() if w['content'] != '2010')
    assert spatial_dob_components(words + (word('1', 140, 40),)) is None


def test_unlabelled_date_requires_exactly_three_ordered_numeric_components():
    numeric = tuple(w for w in observed_words() if w['content'].isdigit())
    assert spatial_dob_components(numeric) == '01/15/2010'
    assert spatial_dob_components(numeric + (word('13', 80, 40),)) is None
    future = tuple(w for w in numeric if w['content'] != '2010') + (word('2070', 140, 40),)
    assert spatial_dob_components(future) is None


def test_azure_backend_preserves_word_polygons():
    from workers.cascade.azure_di_backend import AzureDocumentIntelligenceReadBackend

    backend = AzureDocumentIntelligenceReadBackend('https://example.invalid', 'test')
    evidence = backend._to_evidence({'analyzeResult': {'content': 'YY 2010 DD 15 MM 01',
        'pages': [{'words': list(observed_words())}]}})
    assert evidence.text == 'YY 2010 DD 15 MM 01'
    assert spatial_dob_components(evidence.words) == '01/15/2010'


def test_cached_trocr_loading_does_not_require_hub_metadata(monkeypatch, tmp_path):
    from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter

    calls = []
    model = SimpleNamespace(to=lambda device: None, eval=lambda: None)
    processor = object()
    class Processor:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls.append(('processor', kwargs))
            return processor
    class Model:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls.append(('model', kwargs))
            return model
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        TrOCRProcessor=Processor, VisionEncoderDecoderModel=Model))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        try_to_load_from_cache=lambda *a, **kw: str(tmp_path / 'config.json')))
    adapter = TrOCRAdapter(device='cpu')
    adapter._load()
    assert calls == [('processor', {'local_files_only': True}), ('model', {'local_files_only': True})]
    assert adapter._processor is processor and adapter._model is model


def test_trocr_failed_model_load_does_not_publish_partial_state(monkeypatch, tmp_path):
    from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter

    class Processor:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return object()
    class Model:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            raise OSError('checkpoint unavailable')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        TrOCRProcessor=Processor, VisionEncoderDecoderModel=Model))
    adapter = TrOCRAdapter(model_name=str(tmp_path), device='cpu')
    with pytest.raises(RuntimeError, match='never downloads'):
        adapter._load()
    assert adapter._processor is None and adapter._model is None


def test_absent_local_model_never_invokes_a_remote_repository_loader(monkeypatch):
    from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter

    calls = []
    factory = SimpleNamespace(from_pretrained=lambda *a, **kw: calls.append(a))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        TrOCRProcessor=factory, VisionEncoderDecoderModel=factory))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        try_to_load_from_cache=lambda *a, **kw: None))
    with pytest.raises(RuntimeError, match='never downloads'):
        TrOCRAdapter(model_name='absent-model-test/not-provisioned', device='cpu')._load()
    assert calls == []
