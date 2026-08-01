from workers.table_extraction.token_consensus import (
    TextCandidate,
    fuse_noncritical_description,
)


def test_fuses_independent_description_tokens() -> None:
    value = fuse_noncritical_description([
        TextCandidate("Ancillarv Code Detox", 0.89, "PADDLE_FAMILY"),
        TextCandidate("Ancillary Code Netoy", 0.84, "TESSERACT_FAMILY"),
    ])
    assert value == "Ancillary Code Detox"


def test_requires_independent_architectures() -> None:
    assert fuse_noncritical_description([
        TextCandidate("Ancillarv Code Detox", 0.89, "PADDLE_FAMILY"),
        TextCandidate("Ancillary Code Detox", 0.95, "PADDLE_FAMILY"),
    ]) is None


def test_abstains_on_large_disagreement() -> None:
    assert fuse_noncritical_description([
        TextCandidate("Completely different output", 0.99, "PADDLE_FAMILY"),
        TextCandidate("Ancillary Code Detox", 0.80, "TESSERACT_FAMILY"),
    ]) is None
