"""Configuration errors only; underlying execution exceptions pass through."""


class PipelineConfigurationError(ValueError):
    """The pipeline cannot be assembled unambiguously."""
