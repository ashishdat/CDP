"""Product gates package — similar-sample STP/accuracy enforcement."""

from packages.product_gates.accuracy_accept_policy import (
    AcceptVerdict,
    evaluate_critical_accept,
    filter_auto_fields,
)
from packages.product_gates.similar_sample_gate import (
    ProductGateResult,
    evaluate_similar_sample_gate,
    load_product_contract,
)

__all__ = [
    "AcceptVerdict",
    "ProductGateResult",
    "evaluate_critical_accept",
    "evaluate_similar_sample_gate",
    "filter_auto_fields",
    "load_product_contract",
]
