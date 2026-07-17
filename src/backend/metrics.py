"""Custom Prometheus metrics for the Agentic CI Observatory.

All metrics are registered at import time. Other components populate them;
this module only defines the metric names, help strings, and label sets so
that they are stable from the start.
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Pipeline health
# ---------------------------------------------------------------------------
pipeline_last_success_timestamp = Gauge(
    "pipeline_last_success_timestamp",
    "Timestamp of last successful run",
    ["pipeline"],
)
pipeline_run_duration_seconds = Histogram(
    "pipeline_run_duration_seconds",
    "Duration of pipeline runs in seconds",
    ["pipeline", "status"],
)
pipeline_runs_total = Counter(
    "pipeline_runs_total",
    "Total pipeline runs",
    ["pipeline", "status"],
)
pipeline_failure_streak = Gauge(
    "pipeline_failure_streak",
    "Current consecutive failure count",
    ["pipeline"],
)

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
pipeline_tokens_total = Counter(
    "pipeline_tokens_total",
    "Total tokens used",
    ["pipeline", "model", "skill"],
)
pipeline_cost_usd_total = Counter(
    "pipeline_cost_usd_total",
    "Total cost in USD",
    ["pipeline", "model"],
)
pipeline_skill_duration_seconds = Histogram(
    "pipeline_skill_duration_seconds",
    "Duration of skill execution in seconds",
    ["pipeline", "skill"],
)

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
provenance_runs_with_manifest_total = Counter(
    "provenance_runs_with_manifest_total",
    "Total runs with a run-manifest.json artifact",
    ["pipeline"],
)
provenance_packages_tracked = Gauge(
    "provenance_packages_tracked",
    "Number of tracked packages",
    ["pipeline", "manager"],
)
provenance_containers_tracked = Gauge(
    "provenance_containers_tracked",
    "Number of tracked container images",
    ["pipeline"],
)
sbom_images_total = Gauge(
    "sbom_images_total",
    "Total container images with SBOMs",
)
sbom_vulnerabilities_total = Gauge(
    "sbom_vulnerabilities_total",
    "Total known vulnerabilities",
    ["severity"],
)

# ---------------------------------------------------------------------------
# Collector health
# ---------------------------------------------------------------------------
collector_last_scrape_timestamp = Gauge(
    "collector_last_scrape_timestamp",
    "Timestamp of last collector scrape",
    ["pipeline"],
)
collector_scrape_errors_total = Counter(
    "collector_scrape_errors_total",
    "Total collector scrape errors",
    ["pipeline"],
)

# ---------------------------------------------------------------------------
# Receiver health
# ---------------------------------------------------------------------------
otlp_spans_received_total = Counter(
    "otlp_spans_received_total",
    "Total OTLP spans received",
)
mlflow_runs_received_total = Counter(
    "mlflow_runs_received_total",
    "Total MLflow runs received via push",
)
sbom_push_received_total = Counter(
    "sbom_push_received_total",
    "Total SBOMs received via push",
)

# ---------------------------------------------------------------------------
# Semantic claim consolidation
# ---------------------------------------------------------------------------
claim_candidate_generation_duration_seconds = Histogram(
    "claim_candidate_generation_duration_seconds",
    "Duration of semantic claim candidate generation runs",
)
claim_candidate_shortlist_size = Histogram(
    "claim_candidate_shortlist_size",
    "Mean bounded shortlist size per claim candidate generation batch",
    buckets=(0, 1, 2, 5, 10, 20, 50),
)
claim_candidate_generation_failures_total = Counter(
    "claim_candidate_generation_failures_total",
    "Total semantic claim candidate generation failures",
)
