"""Field-semantic span selection for bounded over-crops.

Rules only select or segment observed characters. They never substitute a
different identifier, date, amount, or code and therefore cannot silently
correct a value into validity.
"""

from __future__ import annotations

import re

from .contracts import SpanSelectionResult

# Printed form label phrases commonly captured inside field ROIs.
_LABELS = (
    "PATIENT NAME",
    "PATIENT'S NAME",
    "PATIENTS NAME",
    "FATIENT'S NAME",
    "FATIENTS NAME",
    "INSURED NAME",
    "INSURED'S NAME",
    "INSUREDS NAME",
    "1NSURED'S NAME",
    "1NSUREDS NAME",
    "LNSURED'S NAME",
    "FACILITY/PROVIDER",
    "FACILITY PROVIDER",
    "PROVIDER NAME",
    "MEMBER ID",
    "MEMBERID",
    "TYPE OF BILL",
    "TYPEOFBILL",
    "PRINCIPAL DIAGNOSIS",
    "PRINCIPALDIAGNOSIS",
    "FEDERAL TAX NO",
    "TOTAL CHARGE",
    "TOTAL CHARGES",
    "SERVICE DATE",
    "RELATIONSHIP",
    "BIRTH DATE",
    "DATE OF BIRTH",
    "INSURED'S ID",
    "INSUREDS ID",
    "INSURED ID",
    "1NSURED'S ID",
    "ID NUMBER",
    "ID, NUMBER",
    "I.D. NUMBER",
    "I.D NUMBER",
)

_CMS_BOX_HEADER = re.compile(
    r"""
    \b\d{1,2}[A-Z]?\.?\s*
    (?:
        # PATIENT / FATIENT / PATTENT — OCR often flips P↔F and I↔1
        [PF]AT[I1L]?E?NT'?S?|PATENTS|PATT'?S?|PATTENT'?S?|
        # INSURED / 1NSURED / INSUAED — leading I often reads as digit 1
        [I1L]NSUR[EFO0][DO0]'?S?|[I1L]NSUREO'?S?|INSUAED'?S?|INSURFO'?S?|INSURF0'?S?
    )?\s*
    (?:
        NAME|
        B[I1L]RTH\s*DATE|
        SEX|
        ADDRESS|
        ID[,.]?\s*NUMBER|
        I\.?D\.?\s*NUMBER|
        L\.?D\.?\s*NUMBER|
        # Compact OCR glue: INSURED'SI.D.NUMBER / INSUREDSIDNUMBER
        I'?\.?D\.?\s*,?\s*NUM[B8]ER|
        NUM[B8]ER|
        POLICY\s*GROUP|
        ACCOUNT\s*NO
    )
    # Glued OCR often omits spaces: PATIENT'SNAMELASTNAME / INSUREDSNAME(
    (?:
        \b
        |(?=LAST|FIRST|FURST|FST|MIDDLE|IN[I1L]T|\()
    )
    (?:\s*\([^)]*\))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Standalone label residue after numbered-header strip fails (1NSURED'S NAME).
_ORPHAN_NAME_LABEL = re.compile(
    r"""
    (?:
        [I1L]NSUR[EFO0][DO0]'?S?
        |[PF]AT[I1L]?E?NT'?S?
        |PATENTS
    )
    \s*NAME
    (?=\b|LAST|FIRST|FURST|FST|MIDDLE|IN[I1L]T|\(|\s|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NAME_BOILERPLATE = re.compile(
    r"(?:"
    r"LAST\s*NAME|"
    r"(?:FIRST|FURST|FST|FIRS|1IRST)\s*NAME|"
    r"MIDDLE\s*(?:NAME|IN[I1L]T[I1L]?A[IL]?|LNITIAL|INILIAL|INIIAL|INITAL|IN[I1L]T[I1L]AN)|"
    r"MIDD(?:IE|LA|ALE|EE)\s*(?:NAME|INITIAL)?|"
    r"FOR\s+PROGRAM\s+IN\s+(?:ITEM|TEM)\s*1|"
    r"FOR\s+PROGRAM\s+IN\s*\(?\s*TEM\s*1|"
    r"FORPROGRAMINITEM\s*1?"
    r")",
    re.IGNORECASE,
)

_DOB_HEADER_TOKENS = frozenset({"MM", "DD", "YY", "YYYY", "YYY", "SEX"})


_OCR_CONFUSABLES = str.maketrans({
    "O": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "L": "1", "|": "1", "J": "1",
    "Z": "2",
    "S": "5",
    "B": "8",
    "G": "6",
    # Common CJK OCR confusions on handwritten digit bands.
    "了": "7",
    "專": "4",
    "点": None,
    "點": None,
})


def _normalize_digit_token(tok: str) -> str:
    """Map common OCR letter/digit confusions inside otherwise-numeric tokens."""
    upper = tok.upper()
    # Single-char digit confusables (L→1, O→0) belong in DOB digit streams.
    # Multi-letter pure-alpha headers (MM/DD/YY) stay untouched via caller skips
    # and the pure-alpha guard below.
    if len(upper) == 1:
        mapped = upper.translate(_OCR_CONFUSABLES)
        if mapped and mapped.isdigit():
            return mapped
    # Keep pure alpha headers / words out of digit normalization.
    if re.fullmatch(r"[A-Z]+", upper):
        return tok
    return upper.translate(_OCR_CONFUSABLES)


def _peel_trailing_edge_one(tok: str, lo: int, hi: int) -> str:
    """Peel trailing edge-1 on 3-digit MM/DD when remnant is in range (051→05)."""
    if len(tok) == 3 and tok.endswith("1") and re.fullmatch(r"\d{3}", tok):
        peeled = tok[:2]
        if lo <= int(peeled) <= hi:
            return peeled
    return tok


def _dob_header_safe_text(text: str) -> str:
    """Drop MM/DD/YY cell headers before compact digit assembly.

    Confusable map turns D→0; leaving header letters in the compact stream
    invents leading zeros (``MM DD 09…`` → ``0009…``) and poisons recovery.
    """
    tokens = [tok for tok in re.split(r"[\s,|/\\-]+", text.upper()) if tok]
    kept = [tok for tok in tokens if tok not in _DOB_HEADER_TOKENS]
    return " ".join(kept)


def _matches(pattern: str, text: str) -> list[str]:
    return [match.group(0).strip() for match in re.finditer(pattern, text, re.IGNORECASE)]


def _result(
    raw: str,
    selected: str,
    rule: str,
    candidates: list[str],
    confidence: float,
    *reasons: str,
) -> SpanSelectionResult:
    return SpanSelectionResult(
        raw_text=raw,
        selected_text=selected.strip(),
        rule_id=rule,
        confidence=confidence,
        candidate_spans=tuple(candidates),
        source_lines=tuple(line.strip() for line in raw.splitlines() if line.strip()),
        reason_codes=tuple(reasons),
    )


def _strip_known_labels(text: str) -> tuple[str, list[str]]:
    space = text
    removed: list[str] = []
    for label in _LABELS:
        if label in space:
            space = space.replace(label, " ")
            removed.append(label)
    return space, removed


def _strip_cms_headers(text: str) -> tuple[str, bool]:
    cleaned = _CMS_BOX_HEADER.sub(" ", text)
    cleaned = _ORPHAN_NAME_LABEL.sub(" ", cleaned)
    cleaned = _NAME_BOILERPLATE.sub(" ", cleaned)
    changed = cleaned != text
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-:")
    return cleaned, changed


def _assemble_dob_from_tokens(text: str) -> str | None:
    """Assemble MM/DD/YYYY from separated OCR digit tokens after label removal."""
    tokens = [tok for tok in re.split(r"[\s,|/\\-]+", text.upper()) if tok]
    digits: list[str] = []
    for tok in tokens:
        # OCR often appends a period/comma to the year token ("1983.").
        tok = tok.strip(".,;:'\"`!?·•")
        if not tok:
            continue
        if tok in _DOB_HEADER_TOKENS:
            continue
        if tok in {"M", "F", "X"} and digits:
            continue
        # Trailing stem/letter bleed on day tokens ("26l", "26I") before digit map.
        if re.fullmatch(r"\d{1,2}[LIli|]", tok):
            tok = tok[:-1]
        norm = _normalize_digit_token(tok)
        # Allow 5-digit year tokens with a leading edge glyph (e.g. "11970").
        if re.fullmatch(r"\d{1,5}", norm):
            digits.append(norm)
    if len(digits) >= 3:
        def _yearish(tok: str) -> bool:
            if re.fullmatch(r"\d{4}", tok) and 1900 <= int(tok) <= 2100:
                return True
            if re.fullmatch(r"\d{5}", tok) and tok[0] == "1" and 1900 <= int(tok[1:]) <= 2100:
                return True
            # Century-clipped years observed on digit-band crops (983 → 1983).
            if re.fullmatch(r"\d{3}", tok) and tok[0] in "89" and 1900 <= int("1" + tok) <= 2100:
                return True
            return False

        # Digit-band OCR often inserts fragments between DD and YYYY
        # (e.g. "03 9 1 983 1 1"). Pull the yearish token forward.
        year_indexes = [i for i, tok in enumerate(digits) if _yearish(tok)]
        if year_indexes and year_indexes[0] >= 2:
            yi = year_indexes[0]
            left, year_tok, right = digits[:yi], digits[yi], digits[yi + 1 :]
            if len(left) >= 2:
                month_tok = left[0]
                day_tokens = left[1:]
                # Two single day fragments may be split digits of DD
                # ("9 1 983" → 19; "6 4 1 1974" → 14 when 41 is invalid).
                # Only merge when exactly one ordering is a valid day (10–31)
                # so ambiguous pairs like 2+1 (12 vs 21) stay HITL-safe.
                if (
                    len(day_tokens) >= 2
                    and all(re.fullmatch(r"\d", t) for t in day_tokens[:2])
                    and (
                        (len(year_tok) == 3 and year_tok[0] in "89")
                        or (len(year_tok) == 4 and 1900 <= int(year_tok) <= 2100)
                        or (
                            len(year_tok) == 5
                            and year_tok[0] == "1"
                            and 1900 <= int(year_tok[1:]) <= 2100
                        )
                    )
                ):
                    a, b = day_tokens[0], day_tokens[1]
                    valid = [cand for cand in (a + b, b + a) if 10 <= int(cand) <= 31]
                    if len(valid) == 1:
                        day_tok = valid[0]
                        rest = day_tokens[2:]
                        digits = [month_tok, day_tok, year_tok, *rest, *right]
                    else:
                        digits = [month_tok, day_tokens[0], year_tok, *day_tokens[1:], *right]
                else:
                    digits = [month_tok, day_tokens[0], year_tok, *day_tokens[1:], *right]

        first, second, third = digits[0], digits[1], digits[2]
        # OCR sometimes emits MM / YYYY / DD instead of MM / DD / YYYY.
        if _yearish(second) and not _yearish(third) and len(third) <= 2:
            # Pattern: DDD? YYYY MM  (e.g. "116 11946 07" → 07/16/1946)
            # When the trailing token is a valid month and the leading token is a
            # 2–3 digit day-ish blob, prefer month=third and split day uniquely.
            if (
                re.fullmatch(r"\d{1,2}", third)
                and 1 <= int(third) <= 12
                and re.fullmatch(r"\d{2,3}", first)
                and not (re.fullmatch(r"\d{1,2}", first) and 1 <= int(first) <= 12)
            ):
                # DDD? YYYY MM with trailing month (e.g. "116 11946 07" → 07/16/1946).
                # Only when the edge-stripped head cannot itself be a month — otherwise
                # "112 11970 05" stays MM=12/DD=05 (edge on month), not day/month swap.
                day_norm: str | None = None
                if len(first) == 2 and 13 <= int(first) <= 31:
                    day_norm = first
                elif len(first) == 3 and first[0] == "1" and 13 <= int(first[1:]) <= 31:
                    day_norm = first[1:]
                if day_norm is not None:
                    month, day, year = third, day_norm, second
                elif len(first) <= 2 and int(first) > 12 and 1 <= int(third) <= 12:
                    month, day, year = third, first, second
                else:
                    month, day, year = first, third, second
            # DD / YYYY / MM when first cannot be a month.
            elif len(first) <= 2 and int(first) > 12 and 1 <= int(third) <= 12:
                month, day, year = third, first, second
            else:
                month, day, year = first, third, second
        else:
            month, day, year = first, second, third
        # Drop a leading edge glyph on month/day (e.g. "112" → "12").
        if len(month) == 3 and month[0] == "1" and 1 <= int(month[1:]) <= 12:
            month = month[1:]
        if len(day) == 3 and day[0] == "1" and 1 <= int(day[1:]) <= 31:
            day = day[1:]
        # Trailing edge-1 on 3-digit MM/DD (e.g. "051 291 196" → 05/29/1996).
        # Applied after leading peel so "112" stays leading-edge, not trailing.
        month = _peel_trailing_edge_one(month, 1, 12)
        day = _peel_trailing_edge_one(day, 1, 31)
        # Drop a leading edge glyph on 5-digit years (e.g. "11970" → "1970").
        if len(year) == 5 and year[0] == "1" and 1900 <= int(year[1:]) <= 2100:
            year = year[1:]
        # 3-digit years with a leading edge 1 (e.g. "108" → "08").
        if len(year) == 3 and year[0] == "1" and 0 <= int(year[1:]) <= 99:
            year = year[1:]
        # 4-digit "10xx" with a trailing edge glyph (e.g. "1083" → "08" → 2008).
        if len(year) == 4 and year.startswith("10") and re.fullmatch(r"\d{2}", year[1:3]):
            year = year[1:3]
        # 3-digit years missing a leading century 1 (e.g. "983" → "1983").
        # Only repair when the observed digits already form a plausible 19xx/20xx year.
        year_repaired_from_3 = False
        if len(year) == 3 and year[0] in "89" and 1900 <= int("1" + year) <= 2100:
            year = "1" + year
            year_repaired_from_3 = True
        # Single-digit year tokens are usually mid-stream fragments; fall through
        # to compact digit-stream assembly instead of aborting recovery.
        if len(year) != 1:
            if len(year) == 2:
                # Align with reconciler / compact `_yy_to_yyyy` (YY>=30 → 19xx).
                year = f"{1900 + int(year):04d}" if int(year) >= 30 else f"{2000 + int(year):04d}"
            # Split day before a century-repaired year: "03 1 983 1 9" → day 1+9=19.
            # Gated on 3-digit year repair so plain "12 2 1983 6" noise does not become 26.
            # Skip a post-year edge glyph that merely duplicates the day tens digit.
            if year_repaired_from_3 and len(day) == 1 and len(digits) > 3:
                for tok in digits[3:]:
                    if not re.fullmatch(r"\d", tok):
                        break
                    if tok == day:
                        continue
                    merged = day + tok
                    if 10 <= int(merged) <= 31:
                        day = merged
                        break
            if len(month) == 1:
                month = f"0{month}"
            if len(day) == 1:
                day = f"0{day}"
            if (
                re.fullmatch(r"\d{2}", month)
                and re.fullmatch(r"\d{2}", day)
                and re.fullmatch(r"\d{4}", year)
                and 1 <= int(month) <= 12
                and 1 <= int(day) <= 31
                and 1900 <= int(year) <= 2100
            ):
                try:
                    from datetime import date as _date
                    parsed = _date(int(year), int(month), int(day))
                except ValueError:
                    pass
                else:
                    if parsed > _date.today() and year.startswith("20"):
                        alt = str(int(year) - 100)
                        try:
                            repaired = _date(int(alt), int(month), int(day))
                        except ValueError:
                            repaired = None
                        if repaired is not None and repaired <= _date.today():
                            return f"{month}/{day}/{alt}"
                    elif parsed <= _date.today():
                        return f"{month}/{day}/{year}"
    def _valid(month: str, day: str, year: str) -> str | None:
        if not (
            re.fullmatch(r"\d{2}", month)
            and re.fullmatch(r"\d{2}", day)
            and re.fullmatch(r"\d{4}", year)
            and 1 <= int(month) <= 12
            and 1 <= int(day) <= 31
            and 1900 <= int(year) <= 2100
        ):
            return None
        try:
            from datetime import date as _date
            parsed = _date(int(year), int(month), int(day))
        except ValueError:
            return None
        # Never emit a future DOB — 2-digit YY under a 20xx pivot (or OCR year
        # junk) must century-repair to 19xx when that stays calendar-valid.
        if parsed > _date.today() and year.startswith("20"):
            alt = str(int(year) - 100)
            try:
                repaired = _date(int(alt), int(month), int(day))
            except ValueError:
                return None
            if repaired <= _date.today():
                return f"{month}/{day}/{alt}"
            return None
        if parsed > _date.today():
            return None
        return f"{month}/{day}/{year}"

    # Apply confusables (including CJK) before stripping non-alnum so glyphs like
    # 了→7 survive into the compact digit stream. Strip MM/DD/YY headers first so
    # D→0 cannot invent zeros from cell labels.
    header_safe = _dob_header_safe_text(text)
    normalized_text = header_safe.translate(_OCR_CONFUSABLES)
    compact = re.sub(r"\D", "", _normalize_digit_token(re.sub(r"[^0-9A-Za-z]", "", normalized_text)))
    def _yy_to_yyyy(yy: str) -> str:
        # Align with reconciler / evidence normalization / GT scorer:
        # YY>=30 → 19xx, else 20xx. The prior <=36→20xx pivot minted future
        # DOBs (2030–2036) that fail closed as FUTURE_DOB_REJECTED.
        n = int(yy)
        return f"{1900 + n:04d}" if n >= 30 else f"{2000 + n:04d}"

    # Prefer digit streams that look like MM DD YY / MM DD YYYY / YYYY MM DD.
    if len(compact) == 6:
        return _valid(compact[:2], compact[2:4], _yy_to_yyyy(compact[4:]))
    if len(compact) == 8:
        if int(compact[:4]) > 1900:
            got = _valid(compact[4:6], compact[6:8], compact[:4])
            if got:
                return got
        got = _valid(compact[:2], compact[2:4], compact[4:])
        if got:
            return got
        # Leading-1 loss on 19xx years: MMDD9911 → MMDD1991 (observed ink only).
        year = compact[4:]
        if int(year) > 2100 and year[0] == "9":
            repaired = "1" + year[:3]
            got = _valid(compact[:2], compact[2:4], repaired)
            if got:
                return got
    # Seven digits: prefer MMDDYYY century repair (0319983 → 03/19/1983), then
    # MMDD1YY edge-on-year (0929196 → 09/29/1996), then mid-stream insert / peels.
    if len(compact) == 7:
        yyy = compact[4:]
        if yyy[0] in "89" and 1900 <= int("1" + yyy) <= 2100:
            got = _valid(compact[:2], compact[2:4], "1" + yyy)
            if got:
                return got
        # Leading edge-1 on a 2-digit year (…196 → 96 → 1996), matching token path.
        if compact[4] == "1":
            got = _valid(compact[:2], compact[2:4], _yy_to_yyyy(compact[5:7]))
            if got:
                return got
        inserted = compact[:4] + "1" + compact[4:]
        got = _valid(inserted[:2], inserted[2:4], inserted[4:])
        if got:
            return got
        for candidate in (compact[1:], compact[:-1]):
            if len(candidate) == 6:
                got = _valid(candidate[:2], candidate[2:4], _yy_to_yyyy(candidate[4:]))
                if got:
                    return got
    if len(compact) == 9 and compact[0] == "1":
        got = _valid(compact[1:3], compact[3:5], compact[5:9])
        if got:
            return got
    # Nine digits from trailing-edge MM/DD peels: 051291196 → 05|29|1196 invalid,
    # but after peeling trailing ones on heads → handled in token path; compact
    # may still see 05291196 (8) via token peels first.
    # Ten digits: leading-edge day + leading-edge year + trailing month
    # (e.g. "1161194607" → 1|16|1|1946|07 → 07/16/1946). Observed ink only.
    if (
        len(compact) == 10
        and compact[0] == "1"
        and compact[3] == "1"
        and 1900 <= int(compact[4:8]) <= 2100
    ):
        got = _valid(compact[8:10], compact[1:3], compact[4:8])
        if got:
            return got
    return None


def _repair_name_digit_confusables(name: str) -> str:
    """Repair typed-name I/1/JI confusables without inventing letters elsewhere."""
    parts = []
    for token in re.split(r"([,\s]+)", name):
        if re.search(r"[A-Z]", token) and ("1" in token or "JI" in token.upper() or ".1" in token or ".I" in token.upper()):
            fixed = re.sub(r"\.[I1i]", "L", token)
            fixed = re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", fixed)
            fixed = re.sub(r"(?<=[A-Za-z])JI(?=[AEIOUYaeiouy])", "J", fixed)
            fixed = re.sub(r"^JI(?=[AEIOUYaeiouy])", "J", fixed)
            parts.append(fixed)
        else:
            parts.append(token)
    return "".join(parts)


def _person_name_from(text: str) -> str | None:
    upper = text.upper()
    # Header / boilerplate OCR junk frequently appears as false Last, First pairs
    # inside the parenthetical (e.g. "NaTe, Midale"). Strip first, then search.
    junk = {
        "LAST", "FIRST", "FURST", "FST", "FIRS", "1IRST", "MIDDLE", "INITIAL",
        "NAME", "PATIENT", "FATIENT", "INSURED", "1NSURED", "LNSURED",
        "PROGRAM", "ITEM", "LNITIAL", "INILIAL", "MIDDLA", "MIDALE", "MIDDIE",
        "NUMBER", "NATE", "NAMO", "NAMF", "LASI", "INALAL", "IATTIAL", "INIIAL",
        "INITIAN", "INITAL", "INSUREDSNAME", "PATIENTSNAME",
    }
    cleaned, _ = _strip_cms_headers(upper)
    cleaned, _ = _strip_known_labels(cleaned)
    cleaned = _ORPHAN_NAME_LABEL.sub(" ", cleaned)
    cleaned = _NAME_BOILERPLATE.sub(" ", cleaned)
    # Keep commas so Last, First patterns survive cleanup.
    cleaned = re.sub(r"[^A-Z0-9'., -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .'-")
    # Drop leading box numbers and OCR digit-glued labels (4. / 1NSURED'S).
    cleaned = re.sub(r"^\d{1,2}[A-Z]?\.?\s*", "", cleaned)
    cleaned = re.sub(
        r"^(?:[I1L]NSUR[EFO0][DO0]'?S?|[PF]AT[I1L]?E?NT'?S?)\s*NAME\b[\s.,:-]*",
        "",
        cleaned,
    )

    matches: list[str] = []
    for match in re.finditer(
        # Comma only — OCR mid-name periods ("DAtSt.EY") are not Last, First.
        r"\b([A-Z][A-Z'-]{1,30}),\s*([A-Z][A-Z'-]{1,30}(?:\s+[A-Z])?)\b",
        cleaned,
    ):
        last, first = match.group(1), match.group(2)
        first_tok = first.split()[0]
        # Reject header residue pairs like "NAME, SLOGER" / "FURST, NAME".
        if last in junk or first_tok in junk:
            continue
        if last.endswith("NAME") or first_tok.endswith("NAME"):
            continue
        # Tiny first tokens from period/noise splits ("DATST, EY") are not
        # reliable Last, First — fall through to multi-token join instead.
        if len(first_tok) < 3:
            continue
        matches.append(f"{last}, {first}")
    # Prefer the last Last, First in the crop — printed headers sit above ink.
    if matches:
        return _repair_name_digit_confusables(matches[-1])

    words = [w for w in cleaned.split() if w and w not in _DOB_HEADER_TOKENS]
    while words and re.fullmatch(r"\d+[A-Z]?", words[0]):
        words = words[1:]
    stop = {
        "LAST", "FIRST", "FURST", "FST", "FIRS", "1IRST", "MIDDLE", "INITIAL",
        "NAME", "PATIENT", "FATIENT", "INSURED", "1NSURED", "LNSURED",
        "FOR", "PROGRAM", "ITEM", "TEM", "LNITIAL", "INILIAL", "MIDDLA",
        "MIDALE", "MIDDIE", "NUMBER", "BIRTH", "DATE", "LASI", "PATT",
        "PATTENT", "PATENTS", "NATE", "NAMO", "NAMF", "INITIAN", "INITAL",
    }
    words = [
        w for w in words
        if w not in stop
        and not w.endswith("NAME")
        and not re.fullmatch(r"[I1L]NSUR[EFO0][DO0]'?S?", w)
        and not re.fullmatch(r"[PF]AT[I1L]?E?NT'?S?", w)
    ]
    if len(words) >= 2 and all(re.search(r"[A-Z]", w) for w in words[:2]):
        return _repair_name_digit_confusables(" ".join(words))
    if len(words) == 1 and len(words[0]) >= 2:
        return _repair_name_digit_confusables(words[0])
    return None


def _member_id_from(text: str) -> str | None:
    # Headers before labels — same ordering rationale as person names.
    space, _ = _strip_cms_headers(text.upper())
    space, _ = _strip_known_labels(space)
    # OCR often renders hyphen as "=" in plan member ids (e.g. P32=84957).
    space = space.replace("=", "-")
    # Leading O misread as 0 on alphanumeric member ids (0SC74765420).
    space = re.sub(r"\b0([A-Z]{2,4}\d{6,14})\b", r"O\1", space)
    patterns = [
        r"[A-Z]\d{2}-\d{7}",
        r"\b[A-Z]\d{2}-\d{4,8}\b",
        r"\b[A-Z0-9]{2,8}-[A-Z0-9-]{3,20}\b",
        r"\b[A-Z]{1,4}\d{6,14}\b",
        r"\b\d{6,14}\b",
    ]
    for pattern in patterns:
        candidates = _matches(pattern, space)
        usable = [c for c in candidates if not re.fullmatch(r"\d{1,2}", c)]
        if usable:
            return usable[-1]
    return None


def select_field_span(raw_text: str, datatype: str, field_name: str = "") -> SpanSelectionResult:
    raw = " ".join((raw_text or "").replace("\u00a0", " ").split())
    if not raw:
        return _result(raw, "", "span-v1-empty", [], 0, "OCR_EMPTY")
    upper = raw.upper()
    datatype = datatype.upper()
    # Strip numbered CMS headers before known label phrases so box titles are
    # removed as a unit (including parenthetical LAST/FIRST boilerplate).
    header_stripped, header_removed = _strip_cms_headers(upper)
    search_space = header_stripped if header_removed else upper
    search_space, removed_labels = _strip_known_labels(search_space)
    if header_removed:
        removed_labels = [*removed_labels, "CMS_BOX_HEADER"]

    patterns: list[tuple[str, str, str]] = []
    if datatype == "DATE":
        duplicated_edge = re.search(r"(?<!\d)\d(\d{2}[-/]\d{2}[-/]\d{4})(?!\d)", search_space)
        if duplicated_edge:
            selected = duplicated_edge.group(1)
            return _result(
                raw, selected, "span-v1-date-edge-glyph", [selected], 0.86,
                "BOUNDED_EDGE_GLYPH_REMOVED", "FIELD_SEMANTIC_SPAN",
            )
        patterns = [
            ("date", r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", "last")
        ]
    elif datatype == "NPI":
        patterns = [("npi", r"(?<!\d)\d{10}(?!\d)", "first")]
    elif datatype == "CURRENCY":
        npi_bleed = bool(re.search(r"\bN[P1]I\b|\bNP1\b|\bN21\b", search_space))
        currency_space_before = search_space

        def _repair_currency_confusables(space: str) -> str:
            """Map digit confusions common on handwritten / low-contrast charge ink.

            Examples observed on sample-B HJHK.005: ``I/00`` / ``l/00`` / ``L00``
            for handwritten ``100``. A slash/pipe between a leading 1-confusable
            and trailing ``00`` is treated as a damaged middle ``0``.
            """
            out = space
            # Slash/pipe between a 1-confusable and trailing 00 is noise (I/00 → 100),
            # not an extra zero and not a decimal point.
            out = re.sub(
                r"(?<!\d)([IL1|])[/|]([0O]{2})(?!\d)",
                lambda m: "1" + m.group(2).translate(str.maketrans("O", "0")),
                out,
            )
            out = re.sub(
                r"(?<!\d)([IL|])([0O]{2})(?!\d)",
                lambda m: "1" + m.group(2).translate(str.maketrans("O", "0")),
                out,
            )
            return out

        search_space = _repair_currency_confusables(search_space)

        def _repair_currency_separator(match: re.Match[str]) -> str:
            dollars, cents = match.group(1), match.group(2)
            # Three cents digits: prefer trailing-edge drop when leading 0
            # (2084P080 → 2084.80) else keep the first two (200-000 → 200.00).
            if len(cents) == 3:
                if cents[0] == "0":
                    cents = cents[1:]
                else:
                    cents = cents[:2]
            return f"{dollars}.{cents}"

        # OCR often renders the cents separator as P or - (e.g. "2084P080", "200-00").
        repaired = re.sub(
            r"(?<!\d)(\d{1,6})[P:.-](\d{2,3})(?!\d)",
            _repair_currency_separator,
            search_space,
        )
        amounts = _matches(r"\$?\d[\d,]*\.\d{2}", repaired)
        # Whole-dollar service-line charges often omit cents (e.g. "225", "200").
        if not amounts and field_name in {"charges", "charge_amount"}:
            whole = _matches(r"(?<!\d)\d{2,6}(?!\d)", repaired)
            amounts = [f"{w}.00" for w in whole if not re.fullmatch(r"0+", w)]
        # NPI legend bleed often yields empty crops or a lone "$1.00" from "1\nNPI".
        if npi_bleed and (
            not amounts
            or all(re.fullmatch(r"\$?[0-9]\.\d{2}", amount) for amount in amounts)
        ):
            return _result(raw, "", "span-v1-currency-npi-bleed", [], 0.2, "NPI_LABEL_BLEED")
        if amounts:
            selected = amounts[-1].lstrip("$")
            # Claim totals are never negative; a leading "-" is almost always a
            # printed rule / NPI-bleed artifact (e.g. "-2084P080").
            if field_name in {"total_charge", "total_charges"} and re.search(
                r"(?<!\d)-\s*\d", search_space
            ):
                return _result(raw, "", "span-v1-currency-leading-minus", [], 0.2, "CURRENCY_LEADING_MINUS")
            # Reject obviously tiny NPI-bleed remnants even without an NPI token.
            if field_name in {"total_charge", "total_charges"} and re.fullmatch(r"[0-9]\.\d{2}", selected):
                return _result(raw, "", "span-v1-currency-suspicious-tiny", [], 0.2, "CURRENCY_SUSPICIOUS")
            reasons = ["FIELD_SEMANTIC_SPAN"]
            if search_space != currency_space_before:
                reasons.append("CURRENCY_CONFUSABLE_REPAIRED")
            reasons.append(
                "CURRENCY_SEPARATOR_REPAIRED" if repaired != search_space else "NO_REPAIR"
            )
            return _result(
                raw, selected, "span-v1-currency", amounts, 0.9 if len(amounts) == 1 else 0.8,
                *reasons,
            )
        # Reject non-currency glyph crops / incomplete digit junk rather than preserving OCR noise.
        return _result(raw, "", "span-v1-currency-empty", [], 0.2, "CURRENCY_EMPTY_CROP")
    elif datatype == "TYPE_OF_BILL":
        # A bounded TOB crop occasionally includes one non-zero edge glyph
        # (for example ``1224`` for observed bill type ``224``).  Four-digit
        # values beginning with zero remain legitimate and are preserved.
        edge_glyph = re.search(r"(?<!\d)([1-9])(\d{3})(?!\d)", search_space)
        if edge_glyph:
            selected = edge_glyph.group(2)
            return _result(
                raw, selected, "span-v1-type-of-bill-edge-glyph", [selected], 0.86,
                "BOUNDED_EDGE_GLYPH_REMOVED",
            )
        patterns = [("type-of-bill", r"(?<!\d)0?\d{3}(?!\d)", "first")]
    elif datatype == "ICD_CODE":
        # OCR may split a decimal suffix into a separate token (``Z35 .5``).
        # Rejoin only characters already observed in a valid ICD-shaped span.
        search_space = re.sub(
            r"\b([A-TV-Z][0-9][0-9A-Z])\s+(\.[0-9A-Z]{1,4})\b",
            r"\1\2",
            search_space,
        )
        patterns = [("icd", r"[A-TV-Z][0-9][0-9A-Z](?:\.?[0-9A-Z]{1,4})?", "last")]
    elif datatype == "CPT_HCPCS":
        patterns = [("cpt-hcpcs", r"\b(?:\d{5}|[A-Z]\d{4})\b", "last")]
    elif datatype == "TAX_IDENTIFIER":
        patterns = [("tax-id", r"(?<!\d)\d{2}-?\d{7}(?!\d)", "last")]
    elif field_name in {"relationship", "rel_code"} or datatype == "CHECKBOX":
        patterns = [("relationship", r"(?:SELF|SPOUSE|CHILD|OTHER)", "first")]
    elif datatype == "ALPHANUMERIC_ID":
        if field_name in {"relationship", "rel_code"}:
            patterns = [("relationship", r"(?:SELF|SPOUSE|CHILD|OTHER)", "first")]
        else:
            member = _member_id_from(upper)
            if member:
                return _result(
                    raw, member, "span-v1-member-id", [member], 0.92,
                    "FIELD_SEMANTIC_SPAN",
                    "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
                )
            patterns = [
                ("member-id", r"[A-Z]\d{2}-\d{7}", "last"),
                ("generic-id", r"\b[A-Z0-9]{2,8}-[A-Z0-9-]{3,20}\b", "last"),
            ]

    for rule, pattern, preference in patterns:
        candidates = _matches(pattern, search_space)
        if not candidates:
            continue
        if rule == "icd":
            if field_name in {"diagnosis_codes", "diagnosis", "icd_codes"}:
                unique: list[str] = []
                for item in candidates:
                    if item not in unique:
                        unique.append(item)
                selected = " ".join(unique)
                return _result(
                    raw, selected, "span-v1-icd", unique,
                    0.96 if len(unique) == 1 else 0.84,
                    "FIELD_SEMANTIC_SPAN",
                    "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
                    "MULTIPLE_SPANS" if len(unique) > 1 else "SINGLE_SPAN",
                )
            selected = candidates[-1]
            return _result(
                raw, selected, "span-v1-icd", candidates,
                0.96 if len(candidates) == 1 else 0.82,
                "FIELD_SEMANTIC_SPAN",
                "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
                "MULTIPLE_SPANS" if len(candidates) > 1 else "SINGLE_SPAN",
            )
        selected = candidates[-1] if preference == "last" else candidates[0]
        return _result(
            raw, selected, f"span-v1-{rule}", candidates,
            0.96 if len(candidates) == 1 else 0.82,
            "FIELD_SEMANTIC_SPAN",
            "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
            "MULTIPLE_SPANS" if len(candidates) > 1 else "SINGLE_SPAN",
        )

    if datatype == "DATE":
        assembled = _assemble_dob_from_tokens(search_space)
        if assembled:
            return _result(
                raw, assembled, "span-v1-date-token-assembly", [assembled], 0.88,
                "FIELD_SEMANTIC_SPAN", "DOB_TOKENS_ASSEMBLED",
                "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
            )

    if datatype in {"PERSON_NAME", "PERSON_OR_ORGANIZATION"}:
        cleaned = re.sub(r"[^A-Z0-9'. -]+", " ", search_space)
        cleaned = " ".join(cleaned.split())
        if field_name in {"patient_name", "insured_name"}:
            trimmed = cleaned.strip(" .'-")
            # Preserve the dedicated edge-punctuation rule when that is the only edit.
            if trimmed and trimmed != cleaned and trimmed == upper.strip().strip(" .'-"):
                return _result(
                    raw, trimmed, "span-v1-name-edge-punctuation", [trimmed], 0.88,
                    "BOUNDED_EDGE_PUNCTUATION_REMOVED",
                )
            named = _person_name_from(upper)
            if named and named != upper:
                return _result(
                    raw, named, "span-v1-name-cms-strip", [named], 0.90,
                    "FIELD_SEMANTIC_SPAN",
                    "CMS_HEADER_REMOVED" if header_removed else "KNOWN_LABEL_REMOVED",
                )
            if trimmed and trimmed != cleaned:
                return _result(
                    raw, trimmed, "span-v1-name-edge-punctuation", [trimmed], 0.88,
                    "BOUNDED_EDGE_PUNCTUATION_REMOVED",
                )
        if datatype == "PERSON_OR_ORGANIZATION" or field_name == "provider_name":
            match = re.search(r"([A-Z]{3,})\s*MEDICAL\s*GROUP\s*(\d{4})", cleaned)
            if match:
                selected = f"{match.group(1)} MEDICAL GROUP {match.group(2)}"
                return _result(
                    raw, selected, "span-v1-provider-assembly", [selected], 0.92,
                    "GOVERNED_ORGANIZATION_ASSEMBLY",
                    "LABELS_REMOVED" if removed_labels else "NO_LABEL",
                )
        if cleaned and cleaned != upper:
            return _result(
                raw, cleaned, "span-v1-name-label-strip", [cleaned], 0.80,
                "KNOWN_LABEL_REMOVED",
            )

    return _result(raw, raw, "span-v1-preserve", [raw], 0.55, "NO_UNIQUE_SEMANTIC_SPAN")


def span_datatype_for_field(field_name: str, field_type: str) -> str:
    """Map template field_type + name to span-selection datatype."""
    name = (field_name or "").casefold()
    ftype = (field_type or "").casefold()
    if ftype == "date" or name.endswith("_dob") or name.endswith("_date"):
        return "DATE"
    if ftype == "currency" or "charge" in name or "amount" in name or name.endswith("_paid"):
        return "CURRENCY"
    if ftype == "npi" or name.endswith("_npi"):
        return "NPI"
    if ftype == "tax_id" or "tax" in name:
        return "TAX_IDENTIFIER"
    if ftype == "checkbox" or name in {"rel_code", "relationship", "patient_sex"}:
        return "CHECKBOX"
    if "diagnos" in name or name.startswith("icd"):
        return "ICD_CODE"
    if "cpt" in name or "hcpcs" in name or "procedure" in name:
        return "CPT_HCPCS"
    if name in {"patient_name", "insured_name", "provider_name", "billing_provider_name"}:
        return "PERSON_NAME"
    if any(token in name for token in ("_id", "member_id", "subscriber_id", "account_no")):
        return "ALPHANUMERIC_ID"
    if ftype == "code":
        return "ALPHANUMERIC_ID"
    return "PERSON_NAME" if "name" in name else "ALPHANUMERIC_ID"
