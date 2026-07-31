from packages.settings import Settings
from workers.unstructured_extraction.production_escalation import (
    build_production_escalator,
)


def test_production_escalator_builds_disabled_without_cloud():
    assert build_production_escalator(Settings(_env_file=None)) is not None


def test_production_escalator_builds_review_only_azure():
    settings = Settings(
        _env_file=None,
        azure_ai_evaluation_enabled=True,
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="secret",
        azure_ai_evaluation_deployment="gpt-4o",
        azure_openai_review_only=True,
    )
    assert build_production_escalator(settings) is not None
