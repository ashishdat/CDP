"""Package intelligence: build claim packages before field extraction."""

from .builder import (
    ClaimPackage,
    PackageIssue,
    PageClass,
    PageIdentity,
    build_claim_package,
    classify_page_signals,
)

__all__ = [
    "ClaimPackage",
    "PackageIssue",
    "PageClass",
    "PageIdentity",
    "build_claim_package",
    "classify_page_signals",
]
