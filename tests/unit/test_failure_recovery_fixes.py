import json
import sys
from dataclasses import dataclass
from types import SimpleNamespace

from PIL import Image

from scripts import ocr_from_geometry as ocr
from scripts.run_hackathon_1000_cascade import _fallback_page_number, _run_stage


def test_timeout_is_isolated_and_next_stage_can_run(tmp_path):
    code, reason = _run_stage(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path / "timeout.log", timeout=0.05,
    )
    assert code == 124 and reason.startswith("REGISTRATION_TIMEOUT:")
    code, _ = _run_stage([sys.executable, "-c", "print('completed')"],
                         tmp_path / "next.log", timeout=10)
    assert code == 0


def test_multipage_fallback_requires_selected_claim_page(tmp_path):
    assert _fallback_page_number(tmp_path, 3) is None
    routing = {"selected_page_number": 3, "needs_review": False,
               "page_roles": {"1": "ATTACHMENT", "3": "CMS1500_CLAIM_PAGE"}}
    path = tmp_path / "page_routing.json"
    path.write_text(json.dumps({"classification": routing}))
    assert _fallback_page_number(tmp_path, 3) == 3
    routing["needs_review"] = True
    path.write_text(json.dumps({"classification": routing}))
    assert _fallback_page_number(tmp_path, 3) is None
    assert _fallback_page_number(tmp_path, 1) == 1


def test_timeout_cannot_consume_partial_geometry(tmp_path, monkeypatch):
    from scripts import run_hackathon_1000_cascade as cascade

    def timeout(command, log, **kwargs):
        application = log.parent.parent / "application"
        application.mkdir()
        (application / "GeometryResult.json").write_text('{"status":"SUCCESS"}')
        return 124, "REGISTRATION_TIMEOUT:180"

    monkeypatch.setattr(cascade, "_run_stage", timeout)
    row = cascade._process_one(document="synthetic", out_dir=tmp_path,
                               dataset_yaml=tmp_path / "dataset.yaml",
                               document_type="AUTO", keep_heavy=True)
    assert row["disposition"] == "APP_FAILURE"
    assert row["registration_reason"] == "REGISTRATION_TIMEOUT"
    assert row["true_stp"] is False


def test_dob_cells_never_borrow_digits_from_another_engine(monkeypatch):
    @dataclass
    class Line:
        text: str

    @dataclass
    class Observation:
        lines: list

    reads = {"rapidocr": iter(["01", "02", "2000"]),
             "paddleocr": iter(["01", "", "2000"])}
    calls = []

    def route(request):
        engine, = request.engine_order
        calls.append(engine)
        text = next(reads[engine])
        attempt = SimpleNamespace(engine=engine, reason="OBSERVED", latency_ns=0,
                                  observation=Observation([Line(text)]))
        return SimpleNamespace(attempts=[attempt])

    monkeypatch.setattr(ocr, "_dob_cell_bboxes", lambda band: {
        "MM": (0, 0, 20, 20), "DD": (20, 0, 40, 20), "YY": (40, 0, 80, 20)})
    image = Image.new("L", (80, 20), 255)
    candidates, _, _ = ocr._recognize_dob_cells(
        image, (0, 0, 80, 20), SimpleNamespace(route=route), ("rapidocr", "paddleocr"))
    assert len(candidates) == 1
    assert candidates[0]["engine"] == "rapidocr"
    assert candidates[0]["span_selection"]["cell_parts"] == {"MM": "01", "DD": "02", "YY": "2000"}
    assert calls == ["rapidocr"] * 3 + ["paddleocr"] * 3


def test_v03_rows_cover_all_six_data_cells_and_exclude_header():
    from packages.templates.registry import TemplateRegistry

    table = TemplateRegistry.load_from_directory().get("cms1500", "03").service_line_region
    bounds = [ocr.service_line_row_bounds(table, row) for row in range(6)]
    # Centers observed in the template reference's six data rows.
    for center, (top, bottom) in zip([1473, 1535, 1597, 1659, 1721, 1783], bounds, strict=True):
        assert top <= center < bottom
    assert bounds[0][0] > 1442  # Printed header bottom.
    assert bounds[-1][1] <= 1812  # Bottom rule before Box 28.
