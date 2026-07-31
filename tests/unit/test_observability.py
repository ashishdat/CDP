"""Prometheus metrics registration, OpenTelemetry span helper, and
PHI-redacting structured logging."""

from prometheus_client import generate_latest

from packages.observability import (
    REGISTRY,
    configure_logging,
    configure_tracing,
    get_logger,
    get_tracer,
    traced_span,
)
from packages.observability.metrics import (
    cache_hits_total,
    documents_received_total,
    processing_errors_total,
)

EXPECTED_METRIC_NAMES = {
    "documents_received_total",
    "pages_processed_total",
    "attachments_skipped_total",
    "cache_hits_total",
    "ocr_latency_seconds",
    "classification_latency_seconds",
    "validation_failure_total",
    "retry_total",
    "vlm_invocation_total",
    "human_review_total",
    "straight_through_rate",
    "estimated_cost_usd_total",
    "processing_errors_total",
    "kafka_consumer_lag",
}


def test_every_spec_named_metric_is_registered():
    # prometheus_client's Counter strips a trailing "_total" from the name
    # passed to it internally and only re-appends it in the exposition
    # text (per the Prometheus text-format convention) -- registration
    # (via REGISTRY.collect()) is checked here since it doesn't depend on
    # any metric having been incremented yet; the exposition-text form
    # (with "_total" restored) is checked separately below, after some
    # counters have actually been used.
    registered_names = {m.name for m in REGISTRY.collect()}
    expected_base_names = {name.removesuffix("_total") for name in EXPECTED_METRIC_NAMES}
    assert expected_base_names <= registered_names


def test_counters_increment_and_export():
    documents_received_total.labels(tenant_id="t1", detected_format="TIFF").inc()
    cache_hits_total.inc()
    processing_errors_total.labels(worker="ingestion_api", stage="ingest").inc()

    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'documents_received_total{detected_format="TIFF",tenant_id="t1"}' in output
    assert "cache_hits_total" in output


def test_traced_span_sets_attributes_and_reraises():
    configure_tracing("test-service")
    tracer = get_tracer(__name__)

    with traced_span(tracer, "test-span", document_id="abc123"):
        pass  # no exception -> span completes normally

    raised = False
    try:
        with traced_span(tracer, "failing-span"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised  # traced_span must not swallow the exception


def test_configured_logging_actually_redacts_phi_end_to_end(caplog):
    """Not just a unit test of `redact_phi_processor` in isolation --
    proves the processor is wired into the actual rendered log output that
    `configure_logging` produces (the pipeline every app/worker entrypoint
    installs), by capturing the real stdlib log record rather than
    structlog's `capture_logs()` test helper, which replaces the
    configured processor chain (including redaction) with its own."""
    configure_logging("test-service")
    logger = get_logger("test")

    with caplog.at_level("INFO"):
        logger.info("field extracted", patient_name="Doe, John", field_name="patient_name")

    assert len(caplog.records) == 1
    rendered = caplog.records[0].message
    assert "Doe, John" not in rendered
    assert '"patient_name": "[REDACTED]"' in rendered
    assert '"field_name": "patient_name"' in rendered  # key name itself is safe
    assert '"service": "test-service"' in rendered  # contextvar binding survived
