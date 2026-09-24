"""Corpus binding — zip ↔ dataset.yaml ↔ selected documents must agree."""

from packages.corpus_binding.binding import (
    CorpusBindingError,
    CorpusBindingResult,
    bind_corpus,
    write_corpus_binding,
)

__all__ = [
    "CorpusBindingError",
    "CorpusBindingResult",
    "bind_corpus",
    "write_corpus_binding",
]
