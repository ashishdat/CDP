"""Deterministic normalizers used only for evaluation comparison."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

Normalizer = Callable[[str | None], str | None]


def text(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", value.strip()) if value and value.strip() else None


def identifier(value: str | None) -> str | None:
    return re.sub(r"[^A-Z0-9]", "", value.upper()) if value else None


def digits(value: str | None) -> str | None:
    result = re.sub(r"\D", "", value or "")
    return result or None


def code(value: str | None) -> str | None:
    result = re.sub(r"[^A-Z0-9.]", "", (value or "").upper())
    return result or None


def date(value: str | None) -> str | None:
    cleaned = text(value)
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()  # noqa: DTZ007
        except ValueError:
            continue
    return cleaned


def amount(value: str | None) -> str | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    if not cleaned:
        return None
    try:
        return format(Decimal(cleaned).quantize(Decimal("0.01")), "f")
    except InvalidOperation:
        return cleaned


BUILTINS: dict[str, Normalizer] = {
    "text": text,
    "identifier": identifier,
    "digits": digits,
    "code": code,
    "date": date,
    "amount": amount,
}


class NormalizerRegistry:
    def __init__(self, field_rules: dict[str, str] | None = None, default: str = "text") -> None:
        self.field_rules = field_rules or {}
        self.default = default

    @classmethod
    def from_yaml(cls, path: str | Path) -> NormalizerRegistry:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(payload.get("fields", {}), payload.get("default", "text"))

    def normalize(self, field_name: str, value: str | None) -> str | None:
        rule = self.field_rules.get(field_name, self.default)
        try:
            return BUILTINS[rule](value)
        except KeyError as exc:
            raise ValueError(f"unknown normalization rule {rule!r}") from exc
