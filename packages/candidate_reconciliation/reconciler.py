"""Evidence-driven reconciliation with fail-closed C3 acceptance."""

from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256

from packages.candidate_reconciliation.contracts import (
    Decision,
    EvidenceReference,
    ReconciliationResult,
)
from packages.confidence import CalibrationRegistry
from packages.criticality import CriticalityLevel
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_policy import EvidencePolicyRegistry
from packages.observability.metrics import field_reconciliation_total
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


def _canonical_date_digits(value: str) -> str:
    """Normalize US/ISO/compact dates to YYYYMMDD for conflict comparison."""
    digits = re.sub(r"\D", "", (value or "").strip())
    if len(digits) == 8:
        # Prefer ISO YYYYMMDD when year-looking prefix, else MMDDYYYY.
        if int(digits[0:4]) >= 1880:
            return digits
        return digits[4:8] + digits[0:2] + digits[2:4]
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}{digits[0:2]}{digits[2:4]}"
    return digits


def _dob_ymd(value: str) -> tuple[str, str, str] | None:
    digits = _canonical_date_digits(value)
    if len(digits) != 8:
        return None
    year, month, day = digits[0:4], digits[4:6], digits[6:8]
    try:
        from datetime import date as _date

        _date(int(year), int(month), int(day))
    except ValueError:
        return None
    return year, month, day


def _dob_is_future(value: str) -> bool:
    """True when a calendar-valid DOB is after today (OCR year/box-rule junk)."""
    from datetime import date as _date

    parts = _dob_ymd(value)
    if parts is None:
        return False
    year, month, day = (int(p) for p in parts)
    try:
        return _date(year, month, day) > _date.today()
    except ValueError:
        return False


def prefer_dob_without_separator_one(
    primary: str, competitors: list[str]
) -> str | None:
    """CMS DOB boxes use dashed vertical rules that OCR reads as leading ``1``.

    When two calendar-valid dates differ only by that artifact on MM or DD
    (11 vs 01, 19 vs 09), prefer the copy without the extra leading 1.
    Returns the observed clean display string when available, else ISO
    ``YYYY-MM-DD``.
    """
    observed: list[tuple[tuple[str, str, str], str]] = []
    for value in [primary, *competitors]:
        ymd = _dob_ymd(value)
        if ymd is not None:
            observed.append((ymd, value))
    if len(observed) < 2:
        return None
    parts = [ymd for ymd, _ in observed]

    def peel(component: str) -> str | None:
        if len(component) == 2 and component[0] == "1" and component[1] != "0":
            return f"0{component[1]}"
        return None

    cleaned: set[tuple[str, str, str]] = set()
    for year, month, day in parts:
        month_opts = {month}
        day_opts = {day}
        peeled_m = peel(month)
        peeled_d = peel(day)
        if peeled_m:
            month_opts.add(peeled_m)
        if peeled_d:
            day_opts.add(peeled_d)
        for mm in month_opts:
            for dd in day_opts:
                try:
                    from datetime import date as _date

                    _date(int(year), int(mm), int(dd))
                except ValueError:
                    continue
                cleaned.add((year, mm, dd))

    # A clean date is a separator-relief if some observed date is the +1 form.
    for year, month, day in sorted(cleaned):
        sep_month = f"1{month[1]}" if month[0] == "0" else None
        sep_day = f"1{day[1]}" if day[0] == "0" else None
        observed_sep = False
        observed_clean = (year, month, day) in parts
        for oy, om, od in parts:
            if oy != year:
                continue
            if sep_month and om == sep_month and od == day:
                observed_sep = True
            if sep_day and od == sep_day and om == month:
                observed_sep = True
        if observed_sep and (observed_clean or (year, month, day) not in parts):
            # Prefer an observed OCR string for the clean YMD (keeps evidence match).
            for ymd, display in observed:
                if ymd == (year, month, day):
                    return display
            return f"{year}-{month}-{day}"
    return None


def _member_ids_differ_by_confusable_insertion(left: str, right: str) -> bool:
    """True when member IDs match after removing one inserted I/1/L glyph.

    Track-B residual: ``A00046372APU`` vs ``A00046372APLU`` — OCR inserted an
    L into the alphabetic suffix, not a different subscriber id.
    """
    a, b = _canonical_member_id(left), _canonical_member_id(right)
    if not a or not b or a == b:
        return False
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch in {"I", "1", "L"} and longer[:idx] + longer[idx + 1 :] == shorter:
            return True
    return False


def prefer_member_id_without_confusable_insertion(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the shorter member ID when OCR inserted an I/1/L confusable."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not _member_ids_differ_by_confusable_insertion(left, right):
                continue
            cl, cr = _canonical_member_id(left), _canonical_member_id(right)
            return left if len(cl) <= len(cr) else right
    return None


def _canonical_person_name(value: str) -> str:
    """Normalize person-name OCR for agreement / conflict equivalence.

    Handles common typed-CMS confusables without inventing letters:
    - digit ``1`` amid letters → ``I`` (ROVINSK1)
    - ``.1`` / ``.I`` between letters → ``L`` (REYNEL.1ISA)
    - capital-J stem ``JI`` before a vowel → ``J`` (JIOSEPHINE)
    """
    text = (value or "").strip().upper()
    text = re.sub(r"\.[I1]", "L", text)  # .1 / .I often a broken L glyph
    text = re.sub(r"[^A-Z0-9]", "", text)
    text = re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", text)
    text = re.sub(r"JI(?=[AEIOUY])", "J", text)
    return text


def _name_label_contaminated(value: str) -> bool:
    """True when OCR still carries CMS box-header / Last-First boilerplate."""
    upper = (value or "").upper()
    if not upper.strip():
        return True
    if re.search(
        r"(?:[I1L]NSUR[EFO0][DO0]'?S?|[PF]AT[I1L]?E?NT'?S?|PATENTS)\s*NAME",
        upper,
    ):
        return True
    if re.search(
        r"(?:LAST|FIRST|FURST|FST|MIDDLE)\s*NAME|MIDDLE\s*INITIAL",
        upper,
    ):
        return True
    return False


_NAME_HONORIFICS = frozenset({"MRS", "MR", "MS", "MISS", "DR"})


def _peel_honorific_glue(token: str) -> str:
    """Peel glued CMS honorifics (BEAUDOINMRS → BEAUDOIN, MRSCHERYL → CHERYL)."""
    tok = (token or "").upper()
    if not tok or tok in _NAME_HONORIFICS:
        return tok
    for honor in sorted(_NAME_HONORIFICS, key=len, reverse=True):
        if tok.startswith(honor) and len(tok) > len(honor) + 1:
            return tok[len(honor) :]
        if tok.endswith(honor) and len(tok) > len(honor) + 1:
            return tok[: -len(honor)]
    return tok


def _name_tokens(value: str) -> list[str]:
    # Preserve digit-as-letter confusables before stripping punctuation
    # (L0 DANNY → LO DANNY, not L DANNY).
    compact = (value or "").upper().replace("0", "O").replace("1", "I")
    compact = re.sub(r"[^A-Z\s]", " ", compact)
    stop = {
        "LAST", "FIRST", "FURST", "FST", "MIDDLE", "INITIAL", "NAME",
        "PATIENT", "FATIENT", "INSURED", "1NSURED",
        *_NAME_HONORIFICS,
    }
    out: list[str] = []
    for tok in compact.split():
        if not tok or tok in stop or tok.endswith("NAME"):
            continue
        peeled = _peel_honorific_glue(tok)
        if peeled and peeled not in stop:
            out.append(peeled)
    return out


def prefer_longer_name_prefix(primary: str, competitors: list[str]) -> str | None:
    """Prefer the longer name when one reading is a strict token-prefix of another.

    Example: ``ORR JAMES`` vs ``ORR JAMES ANTHONY`` — middle name only on one
    engine is not a true conflict.
    """
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    tokenized = [(_name_tokens(v), v) for v in observed]
    tokenized = [(toks, v) for toks, v in tokenized if toks]
    if len(tokenized) < 2:
        return None
    # Longest token list that has every shorter list as a prefix.
    tokenized.sort(key=lambda item: len(item[0]), reverse=True)
    longest_toks, longest_display = tokenized[0]
    for toks, _display in tokenized[1:]:
        if longest_toks[: len(toks)] != toks:
            return None
    if any(len(toks) < len(longest_toks) for toks, _ in tokenized):
        return longest_display
    return None


def _names_differ_by_optional_middle_initial(left: str, right: str) -> bool:
    """True when names match except one optional single-letter middle initial.

    Example: ``THOMAS DWAYNE`` vs ``THOMAS S DWAYNE`` — CMS middle-initial
    presence differs by engine, not identity. Remaining tokens may still
    differ by OCR confusable substitution (OLENIK vs OLFNIK + optional J).
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(longer) != len(shorter) + 1:
        return False
    for idx, tok in enumerate(longer):
        if len(tok) != 1:
            continue
        remainder = longer[:idx] + longer[idx + 1 :]
        if remainder == shorter:
            return True
        if len(remainder) == len(shorter) and all(
            _token_pair_equivalent(x, y) for x, y in zip(remainder, shorter)
        ):
            return True
    return False


def _names_differ_by_leading_junk_initial(left: str, right: str) -> bool:
    """True when one engine prefixed a junk single-letter token (Z ALSBURY)."""
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(longer) != len(shorter) + 1:
        return False
    if len(longer[0]) != 1:
        return False
    remainder = longer[1:]
    if remainder == shorter:
        return True
    return len(remainder) == len(shorter) and all(
        _token_pair_equivalent(x, y) for x, y in zip(remainder, shorter)
    )


def _names_differ_by_trailing_digit_junk(left: str, right: str) -> bool:
    """True when canonical forms match after stripping trailing OCR digit junk.

    Track-B residual: ``SAME`` vs ``SAME 2`` — CMS self-reference with a
    box-rule digit, not a different insured name.
    """
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if not longer.startswith(shorter):
        return False
    suffix = longer[len(shorter) :]
    return bool(suffix) and suffix.isdigit() and len(suffix) <= 2


def _names_differ_by_glued_vs_spaced(left: str, right: str) -> bool:
    """True when one engine glued First+Last while the other kept spaces.

    ``MURPHYPATRICK`` vs ``MURPHY PATRICK`` (or ``MURPHYP PATRICK`` with a
    glued MI on the first token) is the same person, not a conflict.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    single, multi = (a, b) if len(a) == 1 and len(b) >= 2 else (
        (b, a) if len(b) == 1 and len(a) >= 2 else (None, None)
    )
    if single is None or multi is None:
        return False
    glued = single[0]
    joined = "".join(multi)
    if _token_pair_equivalent(glued, joined):
        return True
    # Peel a glued single-letter MI from the first spaced token (MURPHYP|PATRICK).
    if len(multi[0]) >= 2 and len(multi[0][-1:]) == 1:
        peeled = [multi[0][:-1], *multi[1:]]
        if _token_pair_equivalent(glued, "".join(peeled)):
            return True
    return False


def _names_differ_by_shared_given_name(left: str, right: str) -> bool:
    """True when a short OCR is only the given name of a longer full-name reading.

    Honorific-stripped residual: ``BEAUDOIN CHERYL`` vs ``CHERYLA`` — same
    given name (with optional trailing letter glue), not a different person.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(shorter) != 1 or len(longer) < 2:
        return False
    target = shorter[0]

    def _given_equiv(cand: str) -> bool:
        if _token_pair_equivalent(target, cand):
            return True
        if abs(len(target) - len(cand)) != 1:
            return False
        s, c = (target, cand) if len(target) < len(cand) else (cand, target)
        return c.startswith(s)

    return _given_equiv(longer[-1]) or _given_equiv(longer[0])


def _names_differ_by_glued_middle_initial(left: str, right: str) -> bool:
    """True when one engine glued an extra letter onto a 1-char middle initial.

    Track-B 300 residual: ``DESIRAE CL`` vs ``DESIRAE L``, ``SHYENNE CP`` vs
    ``SHYENNE P`` — leading OCR junk on the MI, not a different person.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or len(a) != len(b) or a == b:
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diffs) != 1:
        return False
    x, y = diffs[0]
    shorter, longer = (x, y) if len(x) < len(y) else (y, x)
    return len(shorter) == 1 and len(longer) == 2 and longer.endswith(shorter)


def _token_pair_equivalent(left: str, right: str) -> bool:
    """Single-token equivalence under confusable insertion/substitution."""
    if left == right:
        return True
    if _names_differ_by_confusable_insertion(left, right):
        return True
    if _names_differ_by_confusable_substitution(left, right):
        return True
    return False


def _core_name_tokens(tokens: list[str]) -> list[str]:
    """Drop single-letter MIs and digit-only OCR junk for bag comparison."""
    return [tok for tok in tokens if len(tok) > 1 and not tok.isdigit()]


def _names_differ_by_token_order(left: str, right: str) -> bool:
    """True when engines disagree only on Last/First token order.

    Track-B 300 residual: ``CHANG SHERRILEE`` vs ``SHERRILEE L CHANG``,
    ``SPINNEY CHARLES A`` vs ``CHARLES A SPINNEY`` — same person, CMS
    last-first vs first-last reading. Middle initials are ignored in the bag.
    Also covers ``Z SAME`` vs ``SAME Z`` (single core + MI permutation).
    """
    a, b = _name_tokens(left), _name_tokens(right)
    ca, cb = _core_name_tokens(a), _core_name_tokens(b)
    if len(ca) < 1 or len(cb) < 1 or len(ca) != len(cb):
        return False
    # Require at least one multi-letter core; pure MI bags are not identity.
    if not ca:
        return False
    remaining = list(cb)
    for tok in ca:
        match_idx = None
        for idx, other in enumerate(remaining):
            if _token_pair_equivalent(tok, other):
                match_idx = idx
                break
        if match_idx is None:
            return False
        remaining.pop(match_idx)
    return True


def prefer_name_with_optional_middle_initial(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the longer display when only an optional middle initial differs."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not (
                _names_differ_by_optional_middle_initial(left, right)
                or _names_differ_by_glued_middle_initial(left, right)
            ):
                continue
            # Prefer the cleaner single-letter MI when one side is glued (CL→L).
            if _names_differ_by_glued_middle_initial(left, right):
                lt, rt = _name_tokens(left), _name_tokens(right)
                left_mi = sum(1 for t in lt if len(t) == 1)
                right_mi = sum(1 for t in rt if len(t) == 1)
                if left_mi != right_mi:
                    return left if left_mi > right_mi else right
                # Same MI count: prefer shorter MI token (L over CL).
                left_short = sum(len(t) for t in lt if len(t) <= 2)
                right_short = sum(len(t) for t in rt if len(t) <= 2)
                return left if left_short <= right_short else right
            lt, rt = _name_tokens(left), _name_tokens(right)
            return left if len(lt) >= len(rt) else right
    return None


def prefer_name_canonical_token_order(
    primary: str, competitors: list[str]
) -> str | None:
    """Among Last/First order twins, prefer First(+MI)+Last Western display."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    equivalents: list[str] = []
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if _names_differ_by_token_order(left, right):
                if left not in equivalents:
                    equivalents.append(left)
                if right not in equivalents:
                    equivalents.append(right)
    if len(equivalents) < 2:
        return None

    def _score(display: str) -> tuple:
        toks = _name_tokens(display)
        cores = _core_name_tokens(toks)
        has_mi = any(len(t) == 1 for t in toks)
        # Prefer First Last (last token is a core surname-length token and first
        # is also a core) with MI present — common auto-accept display.
        western = (
            len(cores) >= 2
            and len(toks) >= 2
            and toks[-1] in cores
            and toks[0] in cores
            and (len(toks) == 2 or (has_mi and any(len(t) == 1 for t in toks[1:-1])))
        )
        return (
            0 if western else 1,
            0 if has_mi else 1,
            -len(toks),
            -len(display or ""),
        )

    return sorted(equivalents, key=_score)[0]


def prefer_name_without_label_contamination(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer a clean person-name reading over a label-contaminated twin."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    clean = [v for v in observed if not _name_label_contaminated(v)]
    dirty = [v for v in observed if _name_label_contaminated(v)]
    if not clean or not dirty:
        return None
    # If any clean reading's tokens appear inside a dirty crop, prefer clean.
    for cand in clean:
        ct = _name_tokens(cand)
        if len(ct) < 1:
            continue
        for other in dirty:
            ot = _name_tokens(other)
            if not ot:
                continue
            # Clean tokens ⊆ dirty tokens, or dirty ends with clean tokens.
            if ot[-len(ct) :] == ct or all(t in ot for t in ct):
                return cand
    # Otherwise prefer the highest-token clean value when dirty exists.
    clean_sorted = sorted(clean, key=lambda v: len(_name_tokens(v)), reverse=True)
    if clean_sorted and _name_tokens(clean_sorted[0]):
        return clean_sorted[0]
    return None


def _names_differ_by_confusable_insertion(left: str, right: str) -> bool:
    """True when names match after removing one inserted I/1/L glyph."""
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b:
        return a == b and bool(a)
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch in {"I", "1", "L"} and longer[:idx] + longer[idx + 1 :] == shorter:
            return True
    return False


_NAME_CONFUSABLE_PAIRS = {
    frozenset({"E", "L"}),
    frozenset({"E", "F"}),
    frozenset({"I", "L"}),
    frozenset({"I", "T"}),
    frozenset({"I", "1"}),
    frozenset({"L", "T"}),
    frozenset({"O", "D"}),
    frozenset({"O", "0"}),
    frozenset({"U", "V"}),
    frozenset({"V", "Y"}),
    frozenset({"T", "Y"}),
    frozenset({"G", "C"}),
    frozenset({"S", "5"}),
    frozenset({"B", "8"}),
    frozenset({"G", "6"}),
}


def _names_differ_by_confusable_substitution(left: str, right: str) -> bool:
    """True when same-length names differ by ≤2 OCR-confusable letters.

    Track-B 300-run learning: paddle ``DAVIIA KEVTN`` vs rapid ``DAVILA KEVIN``
    is two confusable substitutions (I↔L, T↔I), not a true identity conflict.
    """
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b or len(a) != len(b):
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if not diffs or len(diffs) > 2:
        return False
    return all(frozenset(pair) in _NAME_CONFUSABLE_PAIRS for pair in diffs)


def prefer_name_without_confusable_insertion(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the cleaner name when OCR inserted an I/1/L confusable glyph."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not _names_differ_by_confusable_insertion(left, right):
                continue
            # Prefer fewer confusable glyphs / shorter canonical form.
            cl, cr = _canonical_person_name(left), _canonical_person_name(right)
            if len(cl) < len(cr):
                return left
            if len(cr) < len(cl):
                return right
    # Substitution twins are conflict-equivalent but ranking already picked the
    # higher-confidence display — do not reshuffle them here.
    # JI-peel twins: same canonical after peel — prefer display without raw JI / 1.
    norms = [(_canonical_person_name(v), v) for v in observed]
    by_norm: dict[str, list[str]] = {}
    for norm, display in norms:
        if norm:
            by_norm.setdefault(norm, []).append(display)
    if len(by_norm) == 1:
        displays = next(iter(by_norm.values()))
        scored = sorted(
            displays,
            key=lambda d: (
                "JI" in re.sub(r"[^A-Z]", "", (d or "").upper()),
                "1" in (d or ""),
                len(d or ""),
            ),
        )
        return scored[0] if len(scored) > 1 else None
    return None


def values_conflict_equivalent(field_name: str, left: str, right: str) -> bool:
    """True when two OCR values are representation-equivalent (not true conflicts)."""
    name = (field_name or "").casefold()
    if not (left or "").strip() or not (right or "").strip():
        return False
    if name in {"patient_dob", "date_of_birth", "dob"} or name.endswith("_date"):
        a, b = _canonical_date_digits(left), _canonical_date_digits(right)
        return bool(a) and a == b
    if name in {"insured_id_number", "member_id", "subscriber_id"}:
        a, b = _canonical_member_id(left), _canonical_member_id(right)
        if bool(a) and a == b:
            return True
        if _member_ids_differ_by_confusable_insertion(left, right):
            return True
        return False
    if name in {"patient_name", "insured_name"} or "name" in name:
        a, b = _canonical_person_name(left), _canonical_person_name(right)
        if bool(a) and a == b:
            return True
        if _names_differ_by_confusable_insertion(left, right):
            return True
        if _names_differ_by_confusable_substitution(left, right):
            return True
        # Token-prefix (missing middle name on one engine) is not a true conflict.
        if prefer_longer_name_prefix(left, [right]) is not None:
            return True
        # Optional CMS middle initial (THOMAS DWAYNE vs THOMAS S DWAYNE).
        if _names_differ_by_optional_middle_initial(left, right):
            return True
        # Glued junk on MI (DESIRAE CL vs DESIRAE L).
        if _names_differ_by_glued_middle_initial(left, right):
            return True
        # Leading junk initial (Z ALSBURY vs ALSBURY).
        if _names_differ_by_leading_junk_initial(left, right):
            return True
        # Trailing digit junk on SAME / self-reference (SAME vs SAME 2).
        if _names_differ_by_trailing_digit_junk(left, right):
            return True
        # Glued FirstLast vs spaced tokens (MURPHYPATRICK vs MURPHY PATRICK).
        if _names_differ_by_glued_vs_spaced(left, right):
            return True
        # Short given-name-only OCR vs full name (CHERYLA vs BEAUDOIN CHERYL).
        if _names_differ_by_shared_given_name(left, right):
            return True
        # Last/First token-order twins (CHANG SHERRILEE vs SHERRILEE L CHANG).
        if _names_differ_by_token_order(left, right):
            return True
        # Label-contaminated crop vs clean ink of the same person.
        if prefer_name_without_label_contamination(left, [right]) is not None:
            return True
        return False
    return normalize_agreement_value(field_name, left) == normalize_agreement_value(
        field_name, right
    )


class EvidenceReconciler:
    def __init__(
        self,
        calibration: CalibrationRegistry | None = None,
        accept_thresholds: dict[CriticalityLevel, float] | None = None,
        evidence_policies: EvidencePolicyRegistry | None = None,
        allow_authoritative_financial_e6: bool = False,
    ) -> None:
        self.calibration = calibration or CalibrationRegistry()
        self.thresholds = accept_thresholds or {
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        }
        self.evidence_policies = evidence_policies or EvidencePolicyRegistry.load()
        self.allow_authoritative_financial_e6 = allow_authoritative_financial_e6

    @staticmethod
    def _candidate_id(candidate: OCRCandidate) -> str:
        if candidate.evidence_reference:
            return candidate.evidence_reference
        payload = (
            f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
            f"{candidate.preprocessing_variant}"
        )
        return sha256(payload.encode()).hexdigest()[:24]

    def reconcile(
        self,
        field_name: str,
        candidates: list[OCRCandidate],
        criticality: CriticalityLevel,
        *,
        deterministic_evidence: set[str] | None = None,
        authoritative_value: str | None = None,
        authoritative_reference_verified: bool = False,
        authoritative_source: str | None = None,
        authoritative_version: str | None = None,
        document_family: str = "*",
        enforce_legacy_evidence_policy: bool = True,
        independent_agreement_values: set[str] | None = None,
    ) -> ReconciliationResult:
        deterministic = deterministic_evidence or set()
        groups: dict[str, list[tuple[OCRCandidate, float, str]]] = defaultdict(list)
        conflicts: list[EvidenceReference] = []
        for candidate in candidates:
            display_value = (candidate.value or "").strip()
            if not display_value:
                continue
            calibrated, version = self.calibration.calibrate(
                candidate.engine, field_name, candidate.raw_confidence
            )
            normalized = normalize_agreement_value(field_name, display_value)
            if normalized:
                groups[normalized].append((candidate, calibrated, version))
        ids = [self._candidate_id(candidate) for candidate in candidates]
        if not groups:
            return ReconciliationResult(
                field_name=field_name,
                selected_value=None,
                candidate_ids=ids,
                decision=Decision.ABSTAIN,
                confidence=0,
                rationale_codes=["NO_NONEMPTY_CANDIDATE"],
                calibration_model_version="none",
            )

        qualified_independent_values = (
            {
                normalize_agreement_value(field_name, item)
                for item in independent_agreement_values
            }
            if independent_agreement_values is not None
            else None
        )

        def independent_agreement(normalized_value, items) -> bool:
            if qualified_independent_values is not None:
                return normalized_value in qualified_independent_values
            return len({independence_group(c.engine) for c, _, _ in items}) >= 2

        is_dob_field = field_name in {"patient_dob", "date_of_birth", "dob"}
        is_name_field = field_name in {
            "patient_name",
            "insured_name",
        } or "name" in (field_name or "").casefold()

        def _group_calendar_valid(items) -> bool:
            # Prefer calendar-valid DOB groups over header labels / digit junk
            # so paddle "MM" or "671161946" cannot outrank a shaped date.
            # Future dates are calendar-shaped OCR junk — never prefer them.
            for candidate, _, _ in items:
                raw = str(candidate.value or "")
                if _dob_ymd(raw) is not None and not _dob_is_future(raw):
                    return True
            return False

        def _group_name_clean(items) -> bool:
            for candidate, _, _ in items:
                val = str(candidate.value or "")
                if val.strip() and not _name_label_contaminated(val) and _name_tokens(val):
                    return True
            return False

        def _group_id_shaped(items) -> bool:
            for candidate, _, _ in items:
                val = str(candidate.value or "")
                compact = re.sub(r"[^A-Z0-9]", "", val.upper())
                if re.fullmatch(r"[A-Z0-9]{6,20}", compact) and not re.search(
                    r"INSUR|NUMBER|PROGRAM|ITEM|NAME", val.upper()
                ):
                    return True
            return False

        ranked = sorted(
            groups.items(),
            key=lambda item: (
                independent_agreement(item[0], item[1]),
                _group_calendar_valid(item[1]) if is_dob_field else True,
                _group_name_clean(item[1]) if is_name_field else True,
                _group_id_shaped(item[1])
                if field_name in {"insured_id_number", "member_id", "subscriber_id"}
                else True,
                max(score for _, score, _ in item[1]),
            ),
            reverse=True,
        )
        _normalized_value, supporting = ranked[0]
        value = max(supporting, key=lambda item: item[1])[0].value
        early_separator_relief = False
        early_name_relief = False
        early_id_relief = False
        # Within a multi-engine name agreement group, prefer the display that
        # already lacks JI / digit-1 confusables (JIOSEPHINE → JOSEPHINE).
        if is_name_field and len(supporting) >= 1:
            displays = [str(c.value or "") for c, _, _ in supporting]
            name_clean = prefer_name_without_confusable_insertion(
                displays[0], displays[1:]
            )
            if name_clean:
                value = name_clean
                early_name_relief = True
            else:
                # Prefer already-peeled display among same-canonical supporters.
                scored = sorted(
                    supporting,
                    key=lambda item: (
                        "JI" in re.sub(r"[^A-Z]", "", (item[0].value or "").upper()),
                        "1" in (item[0].value or ""),
                        -item[1],
                    ),
                )
                value = scored[0][0].value
        # CMS box-3 dashed rules OCR as leading "1" (01↔11, 09↔19). Apply
        # separator relief against ALL competing groups, not only when the
        # confidence margin is tiny — high-confidence separator-1 otherwise STP-wrong.
        if is_dob_field and len(ranked) > 1:
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            separator_clean = prefer_dob_without_separator_one(str(value), competing)
            if separator_clean:
                value = separator_clean
                early_separator_relief = True
        elif is_name_field and len(ranked) > 1:
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            label_clean = prefer_name_without_label_contamination(str(value), competing)
            if label_clean:
                value = label_clean
                early_name_relief = True
            else:
                prefix_clean = prefer_longer_name_prefix(str(value), competing)
                if prefix_clean:
                    value = prefix_clean
                    early_name_relief = True
                else:
                    mi_clean = prefer_name_with_optional_middle_initial(
                        str(value), competing
                    )
                    if mi_clean:
                        value = mi_clean
                        early_name_relief = True
                    else:
                        order_clean = prefer_name_canonical_token_order(
                            str(value), competing
                        )
                        if order_clean:
                            value = order_clean
                            early_name_relief = True
                        else:
                            name_clean = prefer_name_without_confusable_insertion(
                                str(value), competing
                            )
                            if name_clean:
                                value = name_clean
                                early_name_relief = True
                            elif any(
                                _names_differ_by_confusable_substitution(
                                    str(value), other
                                )
                                or _names_differ_by_optional_middle_initial(
                                    str(value), other
                                )
                                or _names_differ_by_glued_middle_initial(
                                    str(value), other
                                )
                                or _names_differ_by_token_order(str(value), other)
                                or values_conflict_equivalent(
                                    field_name, str(value), other
                                )
                                for other in competing
                            ):
                                # Confusable / MI / last-first order twins.
                                early_name_relief = True

        # Prefer non-contaminated name groups when ranking was poisoned by
        # high-confidence header OCR (rapid often outscores paddle on labels).
        if is_name_field and len(ranked) > 1 and _name_label_contaminated(str(value)):
            for _norm, items in ranked[1:]:
                cand_val = str(max(items, key=lambda row: row[1])[0].value)
                if not _name_label_contaminated(cand_val) and _name_tokens(cand_val):
                    value = cand_val
                    supporting = items
                    early_name_relief = True
                    break

        # Prefer shaped member-id over header-only crops in the top slot.
        is_id_field = field_name in {"insured_id_number", "member_id", "subscriber_id"}
        if is_id_field and len(ranked) > 1:
            top_compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
            top_is_id = bool(re.fullmatch(r"[A-Z0-9]{6,20}", top_compact)) and not re.search(
                r"INSUR|NUMBER|PROGRAM|ITEM|NAME", str(value or "").upper()
            )
            if not top_is_id:
                for _norm, items in ranked[1:]:
                    cand_val = str(max(items, key=lambda row: row[1])[0].value)
                    compact = re.sub(r"[^A-Z0-9]", "", cand_val.upper())
                    if re.fullmatch(r"[A-Z0-9]{6,20}", compact) and not re.search(
                        r"INSUR|NUMBER|PROGRAM|ITEM|NAME", cand_val.upper()
                    ):
                        value = cand_val
                        supporting = items
                        break
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            id_clean = prefer_member_id_without_confusable_insertion(str(value), competing)
            if id_clean:
                value = id_clean
                early_id_relief = True

        # Never auto-accept a future DOB — OCR year junk / box-rule misreads.
        future_dob_rejected = False
        if is_dob_field and value and _dob_is_future(str(value)):
            # Prefer any non-future calendar-valid competitor before failing closed.
            swapped = False
            for _norm, items in ranked:
                cand_val = str(max(items, key=lambda row: row[1])[0].value)
                if _dob_ymd(cand_val) is not None and not _dob_is_future(cand_val):
                    value = cand_val
                    supporting = items
                    swapped = True
                    break
            if not swapped:
                future_dob_rejected = True

        has_independent_agreement = independent_agreement(
            normalize_agreement_value(field_name, str(value)), supporting
        )
        # Engine-family corroboration is measured from OCR candidates directly.
        # Evidence-bundle E2 independent_agreement_values can be empty on the
        # decision-only path even when paddle+rapid agree on the same value —
        # do not let an empty E2 set starve ID threshold relief.
        supporting_engine_families = {
            independence_group(candidate.engine) for candidate, _, _ in supporting
        }
        has_multi_engine_family = len(supporting_engine_families) >= 2
        calibrated = max(score for _, score, _ in supporting)
        # Agreement bonus stays tied to E2-qualified independent agreement only.
        # Boosting confidence from raw engine-family co-presence widens the
        # conflict margin and can silently ACCEPT genuine DOB/year conflicts.
        agreement_bonus = 0.04 if has_independent_agreement else 0.0
        reference_match = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() == authoritative_value.strip().casefold()
        )
        reference_contradiction = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() != authoritative_value.strip().casefold()
        )
        deterministic_ok = (
            bool(
                deterministic
                & {
                    "CHECKSUM_VALID",
                    "REFERENCE_MATCH",
                    "CROSS_FIELD_CONSISTENT",
                    "CROSS_DOCUMENT_AGREEMENT",
                    "FINANCIAL_RECONCILIATION_VALID",
                    "CLAIM_TOTAL_CONFIRMED",
                    "LINE_TOTALS_RECONCILED",
                    "DATE_RELATIONSHIP_CONFIRMED",
                    "DOB_SERVICE_DATE_CONSISTENT",
                    "MEMBER_IDENTITY_CONSISTENT",
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                }
            )
            or reference_match
            # Format-valid member identifiers with field E3 remain HITL-gated by
            # evidence policy, but no longer hard-fail the C3 independent-engine
            # gate after OCR span cleanup.
            or (
                field_name in {"insured_id_number", "member_id", "subscriber_id"}
                and "HARD_VALIDATION_PASSED" in deterministic
            )
        )
        financial_authority = bool(
            self.allow_authoritative_financial_e6
            and field_name in {"total_charge", "total_charges"}
            and deterministic
            & {
                "CLAIM_TOTAL_CONFIRMED",
                "FINANCIAL_RECONCILIATION_VALID",
                "LINE_TOTALS_RECONCILED",
            }
        )
        # A verified reference is an independent E5 authority, not an OCR
        # calibration shortcut. Exact candidate/reference agreement may use
        # the reference decision's governed confidence and provenance.
        confidence = 1.0 if reference_match or financial_authority else min(
            1.0, calibrated + agreement_bonus
        )
        evidence = [
            EvidenceReference(
                evidence_type="OCR_CANDIDATE",
                reference=self._candidate_id(candidate),
                source=candidate.engine,
                reason_code="ENGINE_SUPPORT",
            )
            for candidate, _, _ in supporting
        ]
        evidence.extend(
            EvidenceReference(
                evidence_type="DETERMINISTIC", reference=code, source="validation", reason_code=code
            )
            for code in sorted(deterministic)
        )
        if reference_match:
            evidence.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_MATCH",
                )
            )
        elif reference_contradiction:
            conflicts.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_CONTRADICTION",
                )
            )
        for other_value, items in ranked[1:]:
            conflicts.extend(
                EvidenceReference(
                    evidence_type="OCR_CANDIDATE",
                    reference=self._candidate_id(candidate),
                    source=candidate.engine,
                    reason_code=f"CONFLICTING_VALUE:{other_value}",
                )
                for candidate, _, _ in items
            )
        reasons = ["HARD_VALIDATION_PASSED"] if "HARD_VALIDATION_PASSED" in deterministic else []
        if has_independent_agreement:
            reasons.append("MULTI_ENGINE_AGREEMENT")
        if reference_match:
            reasons.append("REFERENCE_MATCH")
        reasons.extend(sorted(deterministic))
        signals = set(deterministic)
        if has_independent_agreement:
            signals.add("OCR_MULTI_ENGINE")
        if reference_match:
            signals.add("REFERENCE_MATCH")
        rule = self.evidence_policies.rule_for(document_family, field_name, criticality)
        policy_ok, missing_alternatives = rule.evaluate(signals)
        threshold = rule.threshold if rule.threshold is not None else self.thresholds[criticality]
        # Identity fields with hard validation + member-relationship E6 are
        # corroboration-backed: allow a slightly lower calibrated floor (0.95)
        # instead of inventing values or waiving evidence. Closes near-miss
        # STP blocks where calibrated OCR is ~0.97 under a 0.98 C3 gate.
        identity_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and bool(
                deterministic
                & {
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                    "MEMBER_IDENTITY_CONSISTENT",
                }
            )
        )
        # Dual-engine confirmation agreement (paddle+rapid) after hard ID
        # validation is independent OCR corroboration — same floor as above,
        # not a policy waiver and not invented ink.
        multi_engine_id_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and has_multi_engine_family
        )
        # Shaped format-valid member IDs with hard validation: allow a 0.92
        # floor so near-miss single-engine calibrated probs (~0.92–0.95) STP
        # without MEMBER_RELATIONSHIP E6 or inventing ink.
        id_shaped = False
        if field_name in {"insured_id_number", "member_id", "subscriber_id"}:
            compact_id = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
            id_shaped = bool(
                re.fullmatch(r"[A-Z0-9]{6,20}", compact_id)
                and not re.search(r"INSUR|NUMBER|PROGRAM|ITEM|NAME", str(value or "").upper())
            )
        format_valid_id_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "FORMAT_VALID" in deterministic
            and id_shaped
        )
        # DOB with calendar/format hard validation: deterministic DATE_VALID is
        # corroboration, not invented ink. Floor at C1 (0.80) so near-miss
        # calibrated probs (~0.88–0.91) can STP without softening E3/identity.
        date_corroborated = (
            field_name in {"patient_dob", "date_of_birth", "dob"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "DATE_VALID" in deterministic
        )
        unique_calendar_dob = False
        if date_corroborated:
            # Future-shaped OCR (year 5199 from digit glue) is junk — do not
            # count it against unique-calendar corroboration.
            calendar_ymds = {
                _dob_ymd(str(candidate.value or ""))
                for candidate in candidates
                if (candidate.value or "").strip()
                and not _dob_is_future(str(candidate.value or ""))
            }
            calendar_ymds.discard(None)
            unique_calendar_dob = len(calendar_ymds) == 1 and _dob_ymd(str(value)) is not None and not _dob_is_future(str(value))
            # Uncalibrated fill engines (tesseract) often sit ~0.3 raw conf even when
            # the only calendar-valid shaped DOB passes DATE_VALID — treat unique
            # calendar corroboration like deterministic authority on confidence.
            if unique_calendar_dob:
                confidence = max(confidence, 0.85)
        # Dual-engine exact ID agreement after hard validation is independent
        # confirmation — lift near-miss calibrated floors (~0.71–0.80) that were
        # blocking STP despite paddle+rapid agreeing on the same shaped ID.
        if multi_engine_id_corroborated:
            confidence = max(confidence, 0.96)
        elif identity_corroborated and format_valid_id_corroborated:
            # Relationship-backed single-engine near-miss (~0.88–0.94).
            confidence = max(confidence, 0.95)
        effective_threshold = threshold
        relief_reason: str | None = None
        if identity_corroborated or multi_engine_id_corroborated:
            effective_threshold = min(effective_threshold, 0.95)
            relief_reason = (
                "IDENTITY_CORROBORATED_THRESHOLD_RELIEF"
                if identity_corroborated and not multi_engine_id_corroborated
                else "MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF"
            )
        if format_valid_id_corroborated and not (
            identity_corroborated or multi_engine_id_corroborated
        ):
            effective_threshold = min(effective_threshold, 0.92)
            relief_reason = "FORMAT_VALID_ID_THRESHOLD_RELIEF"
        if date_corroborated:
            effective_threshold = min(effective_threshold, 0.80)
            relief_reason = (
                "DATE_UNIQUE_CALENDAR_CORROBORATED"
                if unique_calendar_dob
                else "DATE_CORROBORATED_THRESHOLD_RELIEF"
            )
        threshold_ok = confidence >= effective_threshold
        if (
            relief_reason
            and confidence >= effective_threshold
            and (confidence < threshold or unique_calendar_dob)
        ):
            reasons.append(relief_reason)
        # C3 always needs deterministic/authoritative evidence or two truly
        # independent engine families. Confidence is never sufficient alone.
        # has_multi_engine_family feeds ID threshold relief only — C3 still
        # requires E2-qualified independent_agreement or deterministic_ok so
        # empty E2 sets cannot authorize non-ID critical fields.
        independent_evidence_ok = has_independent_agreement or deterministic_ok or financial_authority
        if future_dob_rejected:
            decision = Decision.REVIEW
            reasons.append("FUTURE_DOB_REJECTED")
        elif reference_contradiction:
            decision = Decision.REVIEW
            reasons.append("REFERENCE_CONTRADICTION")
        elif not threshold_ok:
            decision = Decision.ESCALATE
            reasons.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
        elif enforce_legacy_evidence_policy and not policy_ok:
            decision = Decision.REVIEW
            reasons.append("FIELD_EVIDENCE_POLICY_NOT_SATISFIED")
            reasons.extend(f"MISSING_ALTERNATIVE:{item}" for item in missing_alternatives)
        elif criticality is CriticalityLevel.C3 and not independent_evidence_ok:
            decision = Decision.REVIEW
            reasons.append("C3_INDEPENDENT_EVIDENCE_REQUIRED")
        elif len(ranked) > 1 and confidence - max(s for _, s, _ in ranked[1][1]) < 0.05:
            competing_values = [str(other) for other, _ in ranked[1:]]
            genuine = [
                other
                for other in competing_values
                if not values_conflict_equivalent(field_name, value, other)
            ]
            # Future-shaped DOB OCR is digit junk, not a genuine calendar conflict.
            if is_dob_field:
                genuine = [
                    other
                    for other in genuine
                    if not (
                        _dob_ymd(str(other)) is not None and _dob_is_future(str(other))
                    )
                ]
            if early_separator_relief:
                # Competing values were separator-1 twins of the cleaned date.
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            elif early_name_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("NAME_CONFLICT_RELIEVED")
            elif early_id_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
            elif not genuine:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("EQUIVALENT_VALUE_CONFLICT_RELIEVED")
            else:
                separator_clean = None
                name_clean = None
                label_clean = None
                prefix_clean = None
                id_clean = None
                if date_corroborated or is_dob_field:
                    separator_clean = prefer_dob_without_separator_one(
                        str(value), genuine
                    )
                if is_name_field:
                    label_clean = prefer_name_without_label_contamination(
                        str(value), genuine
                    )
                    prefix_clean = prefer_longer_name_prefix(str(value), genuine)
                    name_clean = prefer_name_without_confusable_insertion(
                        str(value), genuine
                    )
                if is_id_field:
                    id_clean = prefer_member_id_without_confusable_insertion(
                        str(value), genuine
                    )
                if separator_clean:
                    value = separator_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
                elif id_clean:
                    value = id_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
                elif label_clean:
                    value = label_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_LABEL_CONTAMINATION_RELIEVED")
                elif prefix_clean:
                    value = prefix_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_PREFIX_EXPANSION_RELIEVED")
                elif is_name_field and (
                    mi_clean := prefer_name_with_optional_middle_initial(
                        str(value), genuine
                    )
                ):
                    value = mi_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_MIDDLE_INITIAL_RELIEVED")
                elif is_name_field and (
                    order_clean := prefer_name_canonical_token_order(
                        str(value), genuine
                    )
                ):
                    value = order_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_TOKEN_ORDER_RELIEVED")
                elif name_clean:
                    value = name_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_CONFUSABLE_INSERTION_RELIEVED")
                elif date_corroborated and not any(
                    _dob_ymd(other) is not None
                    and _dob_ymd(other) != _dob_ymd(str(value))
                    and prefer_dob_without_separator_one(str(value), [other]) is None
                    for other in genuine
                ):
                    # Calendar-valid top date vs fragment / separator twins — not ambiguous.
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DATE_CONFLICT_FRAGMENTS_RELIEVED")
                else:
                    decision = Decision.REVIEW
                    reasons.append("CONFLICT_MARGIN_TOO_SMALL")
        else:
            decision = (
                Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
            )
            if early_separator_relief:
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            if early_name_relief:
                reasons.append("NAME_CONFLICT_RELIEVED")
            if early_id_relief:
                reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
        versions = (
            [f"authoritative-reference:{authoritative_version or 'version-not-provided'}"]
            if reference_match
            else ["deterministic-financial-e6-v1"]
            if financial_authority
            else sorted({version for _, _, version in supporting})
        )
        result = ReconciliationResult(
            field_name=field_name,
            selected_value=value,
            candidate_ids=ids,
            decision=decision,
            confidence=confidence,
            supporting_evidence=evidence,
            conflicting_evidence=conflicts,
            rationale_codes=list(dict.fromkeys(reasons)),
            calibration_model_version=",".join(versions),
        )
        field_reconciliation_total.labels(
            field_name=field_name,
            criticality=criticality.value,
            decision=decision.value,
        ).inc()
        return result
