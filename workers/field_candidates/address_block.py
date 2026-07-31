"""Geometry-preserving reconstruction and deterministic address-block parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass

VALID_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


@dataclass(frozen=True)
class AddressBlock:
    raw_lines: tuple[str, ...]
    addr1: str | None
    addr2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    valid: bool


def reconstruct_lines(tokens: list[dict], *, y_tolerance: float = 0.55) -> list[str]:
    """Cluster by vertical overlap, then sort strictly by x within each line."""
    lines: list[dict] = []
    for token in sorted(tokens, key=lambda item: (item["y0"], item["x0"])):
        height = max(1.0, token["y1"] - token["y0"])
        target = next(
            (line for line in lines if abs(token["y0"] - line["y"]) <= height * y_tolerance),
            None,
        )
        if target is None:
            target = {"y": token["y0"], "tokens": []}
            lines.append(target)
        target["tokens"].append(token)
    return [
        " ".join(item["text"].strip() for item in sorted(line["tokens"], key=lambda t: t["x0"]))
        for line in sorted(lines, key=lambda item: item["y"])
    ]


def parse_address_block(lines: list[str]) -> AddressBlock:
    raw = tuple(line.strip() for line in lines if line.strip())
    content = [
        line for line in raw
        if not re.fullmatch(r"(?i)(city|state|zip code|telephone.*|insured.?s address.*)", line)
    ]
    city = state = zip_code = None
    address_lines = []
    for line in content:
        match = re.fullmatch(
            r"\s*(?P<city>[A-Za-z .'-]+?)[,\s]+(?P<state>[A-Za-z]{2})\s+"
            r"(?P<zip>\d{5}(?:-?\d{4})?)\s*", line,
        )
        if match and match.group("state").upper() in VALID_STATES:
            city = match.group("city").strip().upper()
            state = match.group("state").upper()
            zip_code = re.sub(r"\D", "", match.group("zip"))
        else:
            address_lines.append(line.upper())
    addr1 = address_lines[0] if address_lines else None
    addr2 = address_lines[1] if len(address_lines) > 1 else None
    valid = bool(addr1 and (not state or state in VALID_STATES) and (not zip_code or len(zip_code) in {5, 9}))
    return AddressBlock(raw, addr1, addr2, city, state, zip_code, valid)

