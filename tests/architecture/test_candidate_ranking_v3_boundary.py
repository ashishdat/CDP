import ast
from pathlib import Path


def test_ranking_service_depends_only_on_existing_policy_contracts_and_pipeline():
    path = Path(__file__).resolve().parents[2] / "packages/candidate_ranking.py"
    allowed = {
        "collections.abc",
        "packages.extraction_pipeline.models",
        "packages.extraction_pipeline.registry",
        "packages.extraction_recovery.contracts",
        "packages.extraction_recovery.ranking",
    }
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
