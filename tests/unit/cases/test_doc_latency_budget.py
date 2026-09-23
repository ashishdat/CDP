"""Unit tests for adaptive per-doc latency budget + charge-window early-stop."""

from __future__ import annotations

import time

import pytest

from packages.extraction_recovery.doc_latency_budget import (
    DocLatencyBudget,
    HITL_BUCKET_PRIORITY,
    allow_cloud_residual,
    allow_optional,
    begin_doc_budget,
    hitl_bucket_sort_key,
    reset_doc_budget,
    should_early_stop_charge_windows,
)


@pytest.fixture(autouse=True)
def _clean_budget():
    reset_doc_budget()
    yield
    reset_doc_budget()


def test_soft_skips_optional_hard_keeps_unsettled_critical(monkeypatch):
    monkeypatch.setenv("CDP_DOC_LATENCY_BUDGET", "1")
    monkeypatch.setenv("CDP_DOC_BUDGET_SOFT_SEC", "0.05")
    monkeypatch.setenv("CDP_DOC_BUDGET_HARD_SEC", "0.15")
    budget = begin_doc_budget()
    time.sleep(0.06)
    assert budget.past_soft()
    assert not budget.past_hard()
    assert not allow_optional("openocr_svtr", field_name="charges")
    assert allow_cloud_residual("total_charge", unsettled=True)
    assert allow_cloud_residual("patient_dob", unsettled=True)
    assert allow_cloud_residual("insured_id_number", unsettled=True)
    time.sleep(0.12)
    assert budget.past_hard()
    assert allow_cloud_residual("charges", unsettled=True)
    assert not allow_cloud_residual("insured_name", unsettled=False)
    assert not allow_optional("ppocr_v5_server")


def test_disabled_budget_allows_everything(monkeypatch):
    monkeypatch.setenv("CDP_DOC_LATENCY_BUDGET", "0")
    begin_doc_budget()
    assert allow_optional("openocr_svtr")
    assert allow_cloud_residual("insured_name", unsettled=False)


def test_early_stop_blank_primary():
    assert should_early_stop_charge_windows(
        window_index=0, value=None, dual_local_agree=False, probe_empty=True
    )
    assert not should_early_stop_charge_windows(
        window_index=0, value=None, dual_local_agree=False, probe_empty=False
    )


def test_early_stop_dual_local_shaped():
    assert should_early_stop_charge_windows(
        window_index=0,
        value="150.00",
        dual_local_agree=True,
        probe_empty=False,
    )
    assert not should_early_stop_charge_windows(
        window_index=0,
        value="150.00",
        dual_local_agree=False,
        probe_empty=False,
    )


def test_early_stop_after_soft_with_any_shaped(monkeypatch):
    monkeypatch.setenv("CDP_DOC_LATENCY_BUDGET", "1")
    monkeypatch.setenv("CDP_DOC_BUDGET_SOFT_SEC", "0.01")
    monkeypatch.setenv("CDP_DOC_BUDGET_HARD_SEC", "30")
    begin_doc_budget()
    time.sleep(0.02)
    assert should_early_stop_charge_windows(
        window_index=1,
        value="200.00",
        dual_local_agree=False,
        probe_empty=False,
    )


def test_hitl_bucket_order_charge_before_identity():
    buckets = sorted(HITL_BUCKET_PRIORITY, key=hitl_bucket_sort_key)
    assert buckets[0] == "charge_field_hitl"
    assert buckets[1] == "charge_conflict_margin"
    assert "identity_id" in buckets[:4]
    assert hitl_bucket_sort_key("charge_field_hitl") < hitl_bucket_sort_key(
        "identity_dob"
    )


def test_budget_to_dict_records_skips(monkeypatch):
    monkeypatch.setenv("CDP_DOC_LATENCY_BUDGET", "1")
    monkeypatch.setenv("CDP_DOC_BUDGET_SOFT_SEC", "0.01")
    monkeypatch.setenv("CDP_DOC_BUDGET_HARD_SEC", "30")
    budget = begin_doc_budget()
    time.sleep(0.02)
    assert not allow_optional("insured_name_di_confirm", field_name="insured_name")
    payload = budget.to_dict()
    assert payload["past_soft"] is True
    assert payload["skips"]
    assert payload["skips"][0]["kind"] == "insured_name_di_confirm"


def test_from_env_swaps_hard_below_soft(monkeypatch):
    monkeypatch.setenv("CDP_DOC_LATENCY_BUDGET", "1")
    monkeypatch.setenv("CDP_DOC_BUDGET_SOFT_SEC", "20")
    monkeypatch.setenv("CDP_DOC_BUDGET_HARD_SEC", "10")
    budget = DocLatencyBudget.from_env()
    assert budget.hard_sec >= budget.soft_sec
