from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def normalize_agreement_value(field_name: str, value: str | None) -> str:
    """Canonicalize only representation-level differences for E2 agreement.

    This is deliberately field-aware: stripping a decimal point from money,
    for example, could turn 10.00 and 1000 into a false agreement.
    """
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    name = field_name.casefold()
    if any(token in name for token in ("charge", "amount", "paid", "rate")):
        try:
            number = Decimal(re.sub(r"[^0-9.()-]", "", raw).replace("(", "-").replace(")", ""))
            return format(number.normalize(), "f")
        except (InvalidOperation, ValueError):
            return raw
    if any(token in name for token in ("date", "dob")):
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 8:
            if int(digits[0:4]) >= 1880:
                return digits  # YYYYMMDD
            return digits[4:8] + digits[0:2] + digits[2:4]  # MMDDYYYY → YYYYMMDD
        if len(digits) == 6:
            yy = int(digits[4:6])
            century = 1900 if yy >= 30 else 2000
            return f"{century + yy:04d}{digits[0:2]}{digits[2:4]}"
        return digits
    if any(token in name for token in (
        "member", "insured_id", "subscriber_id", "npi",
    )):
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        if compact.isdigit():
            return compact.lstrip("0") or "0"
        return compact
    if any(token in name for token in (
        "name", "address", "diagnos", "icd", "code", "tax", "bill", "zip", "postal",
    )):
        compact = re.sub(r"[^A-Z0-9.]", "", raw)
        if "name" in name:
            # Align with reconciler person-name confusable peels.
            compact = re.sub(r"\.[I1]", "L", raw)
            compact = re.sub(r"[^A-Z0-9]", "", compact)
            compact = re.sub(r"(?<=[A-Z])0(?=[A-Z]|$)", "O", compact)
            compact = re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", compact)
            compact = re.sub(r"JI(?=[AEIOUY])", "J", compact)
        else:
            compact = re.sub(r"[^A-Z0-9]", "", raw)
        return compact
    return " ".join(raw.split())
