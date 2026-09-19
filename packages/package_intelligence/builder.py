"""Claim package intelligence: page identity before field extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PageClass(StrEnum):
    CMS1500 = "CMS1500"
    UB04 = "UB04"
    STATEMENT = "STATEMENT"
    SUPERBILL = "SUPERBILL"
    EOB = "EOB"
    ATTACHMENT = "ATTACHMENT"
    SEPARATOR = "SEPARATOR"
    NON_CLAIM = "NON_CLAIM"
    UNKNOWN = "UNKNOWN"


class PackageIssue(StrEnum):
    MISSING_PAGE = "MISSING_PAGE"
    DUPLICATE_PAGE = "DUPLICATE_PAGE"
    CONTINUATION_PAGE = "CONTINUATION_PAGE"
    SEPARATOR_DETECTED = "SEPARATOR_DETECTED"
    INCOMPLETE_PACKAGE = "INCOMPLETE_PACKAGE"


@dataclass(frozen=True)
class PageIdentity:
    page_index: int
    page_class: PageClass
    confidence: float
    is_separator: bool = False
    is_continuation: bool = False
    barcode_text: str | None = None
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "page_class": self.page_class.value,
            "confidence": self.confidence,
            "is_separator": self.is_separator,
            "is_continuation": self.is_continuation,
            "barcode_text": self.barcode_text,
            "reasons": list(self.reasons),
        }


@dataclass
class ClaimPackage:
    package_id: str
    claim_id: str
    pages: list[PageIdentity] = field(default_factory=list)
    issues: list[PackageIssue] = field(default_factory=list)
    complete: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "claim_id": self.claim_id,
            "pages": [p.to_dict() for p in self.pages],
            "issues": [i.value for i in self.issues],
            "complete": self.complete,
            "confidence": self.confidence,
        }


_SEPARATOR_HINTS = (
    "SOURCEHOV",
    "SOURCE HOV",
    "DOCUMENT SEPARATOR",
    "BATCH SEPARATOR",
    "THIS PAGE INTENTIONALLY",
)


def classify_page_signals(
    *,
    page_index: int,
    form_family: str | None = None,
    ocr_text: str | None = None,
    barcode_text: str | None = None,
    router_label: str | None = None,
    confidence: float = 0.5,
) -> PageIdentity:
    text = f"{ocr_text or ''} {barcode_text or ''}".upper()
    reasons: list[str] = []
    if any(h in text for h in _SEPARATOR_HINTS) or (
        barcode_text and "SEP" in barcode_text.upper()
    ):
        reasons.append("SEPARATOR_TEXT_OR_BARCODE")
        return PageIdentity(
            page_index=page_index,
            page_class=PageClass.SEPARATOR,
            confidence=max(confidence, 0.8),
            is_separator=True,
            barcode_text=barcode_text,
            reasons=tuple(reasons),
        )

    family = (form_family or router_label or "").upper()
    mapping = {
        "CMS1500": PageClass.CMS1500,
        "CMS-1500": PageClass.CMS1500,
        "UB04": PageClass.UB04,
        "UB-04": PageClass.UB04,
        "ATTACHMENT": PageClass.ATTACHMENT,
        "STATEMENT": PageClass.STATEMENT,
        "SUPERBILL": PageClass.SUPERBILL,
        "EOB": PageClass.EOB,
        "NON_CLAIM": PageClass.NON_CLAIM,
    }
    page_class = PageClass.UNKNOWN
    for key, cls in mapping.items():
        if key in family:
            page_class = cls
            reasons.append(f"ROUTER:{key}")
            break
    if page_class == PageClass.UNKNOWN and "CMS" in text and "1500" in text:
        page_class = PageClass.CMS1500
        reasons.append("OCR_CMS1500")
    if page_class == PageClass.UNKNOWN and ("UB-04" in text or "UB04" in text):
        page_class = PageClass.UB04
        reasons.append("OCR_UB04")

    continuation = "CONTINUED" in text or "PAGE 2" in text or "CONT." in text
    if continuation:
        reasons.append("CONTINUATION_HINT")

    return PageIdentity(
        page_index=page_index,
        page_class=page_class,
        confidence=confidence if page_class != PageClass.UNKNOWN else min(confidence, 0.4),
        is_continuation=continuation,
        barcode_text=barcode_text,
        reasons=tuple(reasons or ("UNKNOWN_PAGE",)),
    )


def build_claim_package(
    *,
    package_id: str,
    claim_id: str,
    pages: list[PageIdentity],
    expected_page_count: int | None = None,
) -> ClaimPackage:
    issues: list[PackageIssue] = []
    seen_classes: dict[str, int] = {}
    for page in pages:
        key = f"{page.page_class.value}:{page.page_index}"
        seen_classes[key] = seen_classes.get(key, 0) + 1
        if page.is_separator:
            issues.append(PackageIssue.SEPARATOR_DETECTED)
        if page.is_continuation:
            issues.append(PackageIssue.CONTINUATION_PAGE)

    # Duplicate detection by identical class+index collisions already handled;
    # also flag duplicate primary claim pages.
    primary = [p for p in pages if p.page_class in {PageClass.CMS1500, PageClass.UB04}]
    if len(primary) > 1 and not any(p.is_continuation for p in primary[1:]):
        # Multiple primary forms without continuation mark → possible duplicate.
        if len({p.page_index for p in primary}) < len(primary):
            issues.append(PackageIssue.DUPLICATE_PAGE)

    if expected_page_count is not None and len(pages) < expected_page_count:
        issues.append(PackageIssue.MISSING_PAGE)
        issues.append(PackageIssue.INCOMPLETE_PACKAGE)

    claim_pages = [
        p
        for p in pages
        if p.page_class
        in {
            PageClass.CMS1500,
            PageClass.UB04,
            PageClass.STATEMENT,
            PageClass.SUPERBILL,
            PageClass.EOB,
            PageClass.ATTACHMENT,
        }
        or p.is_continuation
    ]
    complete = bool(claim_pages) and PackageIssue.MISSING_PAGE not in issues
    if not claim_pages:
        issues.append(PackageIssue.INCOMPLETE_PACKAGE)
        complete = False

    conf = (
        sum(p.confidence for p in pages) / len(pages) if pages else 0.0
    )
    return ClaimPackage(
        package_id=package_id,
        claim_id=claim_id,
        pages=list(pages),
        issues=list(dict.fromkeys(issues)),
        complete=complete,
        confidence=float(conf),
    )
