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
    "INSURED NAME",
    "INSURED'S NAME",
    "INSUREDS NAME",
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
    "ID NUMBER",
    "ID, NUMBER",
    "I.D. NUMBER",
    "I.D NUMBER",
)

_CMS_BOX_HEADER = re.compile(
    r"""
    \b\d{1,2}[A-Z]?\.?\s*
    (?:PATIENT'?S?|INSURED'?S?|INSUREO'?S?|PATENTS|INSUREO)?\s*
    (?:
        NAME|
        B[I1L]RTH\s*DATE|
        SEX|
        ADDRESS|
        ID[,.]?\s*NUMBER|
        I\.?D\.?\s*NUMBER|
        POLICY\s*GROUP|
        ACCOUNT\s*NO
    )
    \b
    (?:\s*\([^)]*\))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NAME_BOILERPLATE = re.compile(
    r"\b(?:"
    r"LAST\s*NAME|FIRST\s*NAME|MIDDLE\s*(?:NAME|IN[I1L]T[I1L]?A[IL]?|LNITIAL|INILIAL|INIIAL|INITAL)|"
    r"FOR\s+PROGRAM\s+IN\s+(?:ITEM|TEM)\s*1|"
    r"FOR\s+PROGRAM\s+IN\s*\(?\s*TEM\s*1"
    r")\b",
    re.IGNORECASE,
)

_DOB_HEADER_TOKENS = frozenset({"MM", "DD", "YY", "YYYY", "YYY", "SEX"})


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
    cleaned = _NAME_BOILERPLATE.sub(" ", cleaned)
    changed = cleaned != text
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-:")
    return cleaned, changed


def _assemble_dob_from_tokens(text: str) -> str | None:
    """Assemble MM/DD/YYYY from separated OCR digit tokens after label removal."""
    tokens = [tok for tok in re.split(r"[\s,|/\\-]+", text.upper()) if tok]
    digits: list[str] = []
    for tok in tokens:
        if tok in _DOB_HEADER_TOKENS:
            continue
        if tok in {"M", "F", "X"} and digits:
            continue
        # Allow 5-digit year tokens with a leading edge glyph (e.g. "11970").
        if re.fullmatch(r"\d{1,5}", tok):
            digits.append(tok)
    if len(digits) >= 3:
        def _yearish(tok: str) -> bool:
            if re.fullmatch(r"\d{4}", tok) and 1900 <= int(tok) <= 2100:
                return True
            if re.fullmatch(r"\d{5}", tok) and tok[0] == "1" and 1900 <= int(tok[1:]) <= 2100:
                return True
            return False

        first, second, third = digits[0], digits[1], digits[2]
        # OCR sometimes emits MM / YYYY / DD instead of MM / DD / YYYY.
        if _yearish(second) and not _yearish(third) and len(third) <= 2:
            month, day, year = first, third, second
        else:
            month, day, year = first, second, third
        # Drop a leading edge glyph on month/day (e.g. "112" → "12").
        if len(month) == 3 and month[0] == "1" and 1 <= int(month[1:]) <= 12:
            month = month[1:]
        if len(day) == 3 and day[0] == "1" and 1 <= int(day[1:]) <= 31:
            day = day[1:]
        # Drop a leading edge glyph on 5-digit years (e.g. "11970" → "1970").
        if len(year) == 5 and year[0] == "1" and 1900 <= int(year[1:]) <= 2100:
            year = year[1:]
        if len(year) == 1:
            return None
        if len(year) == 2:
            year = f"20{year}" if int(year) <= 36 else f"19{year}"
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
        return f"{month}/{day}/{year}"

    compact = re.sub(r"\D", "", text)
    if len(compact) == 6:
        return _valid(compact[:2], compact[2:4], f"20{compact[4:]}")
    if len(compact) == 8:
        if int(compact[:4]) > 1900:
            return _valid(compact[4:6], compact[6:8], compact[:4])
        return _valid(compact[:2], compact[2:4], compact[4:])
    return None


def _person_name_from(text: str) -> str | None:
    upper = text.upper()
    # Prefer an explicit Last, First pattern anywhere in the crop.
    junk = {
        "LAST", "FIRST", "MIDDLE", "INITIAL", "NAME", "PATIENT", "INSURED",
        "PROGRAM", "ITEM", "LNITIAL", "INILIAL", "MIDDLA", "NUMBER",
    }
    for match in re.finditer(
        r"\b([A-Z][A-Z'-]{1,30})[,.]\s*([A-Z][A-Z'-]{1,30}(?:\s+[A-Z])?)\b",
        upper,
    ):
        last, first = match.group(1), match.group(2)
        if last not in junk and first.split()[0] not in junk:
            return f"{last}, {first}"
    cleaned, _ = _strip_known_labels(upper)
    cleaned, _ = _strip_cms_headers(cleaned)
    cleaned = _NAME_BOILERPLATE.sub(" ", cleaned)
    cleaned = re.sub(r"[^A-Z0-9'. -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .'-")
    match = re.search(
        r"([A-Z][A-Z'-]{1,30})[,.]\s*([A-Z][A-Z'-]{1,30}(?:\s+[A-Z])?)$",
        cleaned,
    )
    if match:
        return f"{match.group(1)}, {match.group(2)}"
    words = [w for w in cleaned.split() if w and w not in _DOB_HEADER_TOKENS]
    while words and re.fullmatch(r"\d+[A-Z]?", words[0]):
        words = words[1:]
    stop = {
        "LAST", "FIRST", "MIDDLE", "INITIAL", "NAME", "PATIENT", "INSURED",
        "FOR", "PROGRAM", "ITEM", "TEM", "LNITIAL", "INILIAL", "MIDDLA",
        "NUMBER", "BIRTH", "DATE",
    }
    words = [w for w in words if w not in stop]
    if len(words) >= 2 and all(re.search(r"[A-Z]", w) for w in words[:2]):
        return " ".join(words)
    if len(words) == 1 and len(words[0]) >= 2:
        return words[0]
    return None


def _member_id_from(text: str) -> str | None:
    space, _ = _strip_known_labels(text.upper())
    space, _ = _strip_cms_headers(space)
    patterns = [
        r"[A-Z]\d{2}-\d{7}",
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
    search_space, removed_labels = _strip_known_labels(upper)
    header_stripped, header_removed = _strip_cms_headers(search_space)
    if header_removed:
        search_space = header_stripped
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
        amounts = _matches(r"\$?\d[\d,]*\.\d{2}", search_space)
        # NPI legend bleed often yields empty crops or a lone "$1.00" from "1\nNPI".
        if npi_bleed and (
            not amounts
            or all(re.fullmatch(r"\$?[0-9]\.\d{2}", amount) for amount in amounts)
        ):
            return _result(raw, "", "span-v1-currency-npi-bleed", [], 0.2, "NPI_LABEL_BLEED")
        # Reject non-currency glyph crops (e.g. CJK dash "一") with no digit amount.
        if not amounts and not re.search(r"\d", search_space):
            return _result(raw, "", "span-v1-currency-empty", [], 0.2, "CURRENCY_EMPTY_CROP")
        # Lone digit clusters without decimals are not claim totals.
        if not amounts and re.fullmatch(r"[\d\s]+", search_space or ""):
            return _result(raw, "", "span-v1-currency-incomplete", [], 0.2, "CURRENCY_INCOMPLETE")
        patterns = [("currency", r"\$?\d[\d,]*\.\d{2}", "last")]
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
