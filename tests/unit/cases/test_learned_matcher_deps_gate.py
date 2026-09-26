"""Learned matcher must no-op when LightGlue optional deps are missing."""

from __future__ import annotations

import packages.recovery.azure_di_meter as meter
from packages.recovery import learned_matcher as lm


def test_learned_matcher_enabled_false_without_deps(monkeypatch):
    monkeypatch.delenv("CDP_LEARNED_MATCHER", raising=False)
    monkeypatch.setattr(lm, "learned_matcher_deps_available", lambda: False)
    assert meter.learned_matcher_enabled() is False


def test_learned_matcher_enabled_respects_env_off(monkeypatch):
    monkeypatch.setenv("CDP_LEARNED_MATCHER", "0")
    monkeypatch.setattr(lm, "learned_matcher_deps_available", lambda: True)
    assert meter.learned_matcher_enabled() is False


def test_learned_matcher_enabled_true_with_deps(monkeypatch):
    monkeypatch.setenv("CDP_LEARNED_MATCHER", "1")
    monkeypatch.setattr(lm, "learned_matcher_deps_available", lambda: True)
    assert meter.learned_matcher_enabled() is True
