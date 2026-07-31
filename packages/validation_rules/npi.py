"""NPI (National Provider Identifier) check-digit validation.

The NPI check digit uses a fixed-prefix Luhn (mod 10) algorithm: prepend
the constant `80840` (the NPI "prefix" per the CMS/NPPES specification) to
the 10-digit NPI, then the resulting 15-digit number must pass a standard
Luhn check. This is syntactic/checksum validation only -- it does not
confirm the NPI is *assigned* (that would require an NPPES registry
lookup, out of scope here).
"""

from __future__ import annotations

_NPI_PREFIX = "80840"


def is_valid_npi(npi: str) -> bool:
    if not npi.isdigit() or len(npi) != 10:
        return False
    return _luhn_checksum(_NPI_PREFIX + npi) % 10 == 0


def _luhn_checksum(digits_str: str) -> int:
    digits = [int(d) for d in digits_str]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total
