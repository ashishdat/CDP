"""Hybrid escalation-order model router: a pure decision function (no
model calls) picking the next extraction stage per field. See
docs/ARCHITECTURE.md §9 for the full escalation order and rationale."""

from packages.model_router.cost_table import DEFAULT_COST_TABLE, estimated_cost
from packages.model_router.inputs import RouterInput
from packages.model_router.router import ModelRouter

__all__ = ["DEFAULT_COST_TABLE", "ModelRouter", "RouterInput", "estimated_cost"]
