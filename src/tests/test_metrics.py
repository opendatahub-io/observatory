import pytest


@pytest.mark.asyncio
async def test_custom_metrics_registered(client):
    """Verify that all custom Observatory metrics appear in /metrics output."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200

    # Pipeline health
    assert "pipeline_runs_total" in resp.text
    assert "pipeline_last_success_timestamp" in resp.text
    assert "pipeline_run_duration_seconds" in resp.text
    assert "pipeline_failure_streak" in resp.text

    # Telemetry
    assert "pipeline_tokens_total" in resp.text
    assert "pipeline_cost_usd_total" in resp.text
    assert "pipeline_skill_duration_seconds" in resp.text

    # Provenance
    assert "provenance_runs_with_manifest_total" in resp.text
    assert "provenance_packages_tracked" in resp.text
    assert "provenance_containers_tracked" in resp.text
    assert "sbom_images_total" in resp.text
    assert "sbom_vulnerabilities_total" in resp.text

    # Collector health
    assert "collector_last_scrape_timestamp" in resp.text
    assert "collector_scrape_errors_total" in resp.text

    # Receiver health
    assert "otlp_spans_received_total" in resp.text
    assert "mlflow_runs_received_total" in resp.text
    assert "sbom_push_received_total" in resp.text
