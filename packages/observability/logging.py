"""Structured logging setup, shared by every app/worker. PHI redaction
(`packages.security.redact_phi_processor`) is wired in here, not left as
an unused utility -- `configure_logging()` is what every service's
entrypoint calls, so redaction is active by construction rather than by
each service remembering to add it.
"""

from __future__ import annotations

import logging

import structlog

from packages.security.redaction import redact_phi_processor


def configure_logging(service_name: str, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_phi_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
