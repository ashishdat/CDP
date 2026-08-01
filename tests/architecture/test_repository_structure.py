"""Architecture boundaries are part of the production contract."""

from scripts.check_architecture import dependency_errors, tracked_artifact_errors


def test_runtime_dependency_direction() -> None:
    assert dependency_errors() == []


def test_private_and_generated_artifacts_are_not_tracked() -> None:
    assert tracked_artifact_errors() == []
