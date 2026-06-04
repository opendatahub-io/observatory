"""Tests for the OTLP HTTP JSON receiver at /v1/traces."""

import json

import pytest

from backend.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_otlp_payload(
    service_name="test-service",
    trace_id="abc123def456",
    span_id="span001",
    parent_span_id="",
    name="test.operation",
    start_nano="1716883200000000000",
    end_nano="1716886800000000000",
    status_code=1,
    attributes=None,
):
    """Build a minimal OTLP JSON payload."""
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": name,
        "startTimeUnixNano": start_nano,
        "endTimeUnixNano": end_nano,
        "status": {"code": status_code},
        "attributes": attributes or [],
    }
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": service_name},
                        }
                    ]
                },
                "scopeSpans": [{"spans": [span]}],
            }
        ]
    }


SAMPLE_PIPELINE = {
    "slug": "rfe-review",
    "name": "RFE Review",
    "description": "Review pipeline",
    "owner": "team-ai",
    "repo_url": "https://github.com/example/rfe-review",
    "platform": "github",
}

TOKEN_COST_ATTRS = [
    {"key": "llm.token_count.prompt", "value": {"intValue": "120000"}},
    {"key": "llm.token_count.completion", "value": {"intValue": "22000"}},
    {"key": "gen_ai.usage.cost", "value": {"doubleValue": 4.23}},
    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-20250514"}},
]


# ---------------------------------------------------------------------------
# Test: Valid OTLP JSON stores spans in DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_valid_otlp_stores_span(client):
    payload = _make_otlp_payload()

    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {}

    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM telemetry_spans")
    count = (await cursor.fetchone())[0]
    assert count == 1

    cursor = await db.execute("SELECT * FROM telemetry_spans")
    row = await cursor.fetchone()
    assert row["trace_id"] == "abc123def456"
    assert row["span_id"] == "span001"
    assert row["operation_name"] == "test.operation"
    assert row["service_name"] == "test-service"
    assert row["status_code"] == "OK"
    assert row["start_time"] is not None
    assert row["end_time"] is not None
    assert row["duration_ms"] is not None
    assert row["duration_ms"] == 3600000  # 1 hour in ms


# ---------------------------------------------------------------------------
# Test: Pipeline correlation via service.name -> pipelines.slug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_correlation(client):
    # Create the pipeline first
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    # Post OTLP trace with service.name matching the slug
    payload = _make_otlp_payload(
        service_name="rfe-review",
        trace_id="trace-correlated-001",
        span_id="span-corr-001",
        name="rfe.review",
    )
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()

    # Check span has pipeline_run_id set
    cursor = await db.execute("SELECT * FROM telemetry_spans WHERE trace_id = ?", ("trace-correlated-001",))
    span = await cursor.fetchone()
    assert span["pipeline_run_id"] is not None

    # Verify pipeline_run was created with correct pipeline_id
    cursor = await db.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (span["pipeline_run_id"],)
    )
    run = await cursor.fetchone()
    assert run["pipeline_id"] == pipeline_id
    assert run["external_id"] == "trace-correlated-001"
    assert run["status"] == "trace"


# ---------------------------------------------------------------------------
# Test: Uncorrelated spans stored with null pipeline_run_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uncorrelated_span_stored_with_null_run_id(client):
    # service.name does not match any pipeline slug
    payload = _make_otlp_payload(
        service_name="no-such-pipeline",
        trace_id="trace-orphan-001",
    )
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM telemetry_spans WHERE trace_id = ?", ("trace-orphan-001",)
    )
    span = await cursor.fetchone()
    assert span is not None
    assert span["pipeline_run_id"] is None
    assert span["service_name"] == "no-such-pipeline"


# ---------------------------------------------------------------------------
# Test: Token/cost extraction into telemetry_summaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_cost_extraction(client):
    # Create pipeline to enable correlation (required for summary creation)
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201

    payload = _make_otlp_payload(
        service_name="rfe-review",
        trace_id="trace-tokens-001",
        span_id="span-tok-001",
        name="rfe.review",
        attributes=TOKEN_COST_ATTRS,
    )
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()

    # Find the pipeline_run
    cursor = await db.execute(
        "SELECT pipeline_run_id FROM telemetry_spans WHERE trace_id = ?",
        ("trace-tokens-001",),
    )
    span = await cursor.fetchone()
    pipeline_run_id = span["pipeline_run_id"]
    assert pipeline_run_id is not None

    # Check telemetry_summaries
    cursor = await db.execute(
        "SELECT * FROM telemetry_summaries WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    )
    summary = await cursor.fetchone()
    assert summary is not None
    assert summary["input_tokens"] == 120000
    assert summary["output_tokens"] == 22000
    assert summary["total_tokens"] == 142000
    assert abs(summary["cost_usd"] - 4.23) < 0.01
    assert summary["model"] == "claude-sonnet-4-20250514"
    assert summary["skill_name"] == "rfe.review"
    assert summary["source"] == "otlp"
    assert summary["duration_ms"] == 3600000


# ---------------------------------------------------------------------------
# Test: Empty payload returns 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_payload_returns_200(client):
    resp = await client.post("/v1/traces", json={})
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_empty_resource_spans_returns_200(client):
    resp = await client.post("/v1/traces", json={"resourceSpans": []})
    assert resp.status_code == 200
    assert resp.json() == {}


# ---------------------------------------------------------------------------
# Test: Malformed payload handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_returns_200(client):
    resp = await client.post(
        "/v1/traces",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_non_dict_body_returns_200(client):
    resp = await client.post("/v1/traces", json=["not", "a", "dict"])
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_invalid_span_entries_skipped(client):
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "spans": [
                            "not-a-span",
                            42,
                            None,
                            {
                                "traceId": "valid-trace",
                                "spanId": "valid-span",
                                "name": "valid.op",
                                "startTimeUnixNano": "1716883200000000000",
                                "endTimeUnixNano": "1716886800000000000",
                                "status": {"code": 1},
                            },
                        ]
                    }
                ],
            }
        ]
    }
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM telemetry_spans")
    count = (await cursor.fetchone())[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Test: Span query endpoint returns stored spans
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_query_endpoint(client):
    # Create a pipeline and post spans
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201

    # Post two spans with the same trace
    for i in range(3):
        payload = _make_otlp_payload(
            service_name="rfe-review",
            trace_id="trace-query-001",
            span_id=f"span-q-{i:03d}",
            name=f"operation.{i}",
            start_nano=str(1716883200000000000 + i * 1000000000),
            end_nano=str(1716883200000000000 + (i + 1) * 1000000000),
        )
        resp = await client.post("/v1/traces", json=payload)
        assert resp.status_code == 200

    # Find the pipeline_run_id
    db = await get_db()
    cursor = await db.execute(
        "SELECT pipeline_run_id FROM telemetry_spans WHERE trace_id = ? LIMIT 1",
        ("trace-query-001",),
    )
    row = await cursor.fetchone()
    run_id = row["pipeline_run_id"]
    assert run_id is not None

    # Query spans via the endpoint
    resp = await client.get(f"/api/telemetry/spans/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "spans" in body
    assert len(body["spans"]) == 3

    # Spans should be ordered by start_time
    for i, span in enumerate(body["spans"]):
        assert span["span_id"] == f"span-q-{i:03d}"
        assert span["operation_name"] == f"operation.{i}"
        assert span["trace_id"] == "trace-query-001"


@pytest.mark.asyncio
async def test_span_query_empty_run(client):
    """Query for a non-existent run_id returns empty list."""
    resp = await client.get("/api/telemetry/spans/99999")
    assert resp.status_code == 200
    body = resp.json()
    assert body["spans"] == []


# ---------------------------------------------------------------------------
# Test: Multiple spans in single request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_spans_single_request(client):
    """Multiple spans in one OTLP payload are all stored."""
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "multi-service"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace-multi",
                                "spanId": f"span-m-{i:03d}",
                                "name": f"op.{i}",
                                "startTimeUnixNano": "1716883200000000000",
                                "endTimeUnixNano": "1716886800000000000",
                                "status": {"code": 0},
                            }
                            for i in range(5)
                        ]
                    }
                ],
            }
        ]
    }
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM telemetry_spans WHERE trace_id = ?",
        ("trace-multi",),
    )
    count = (await cursor.fetchone())[0]
    assert count == 5


# ---------------------------------------------------------------------------
# Test: Span attributes stored as JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_attributes_stored_as_json(client):
    attrs = [
        {"key": "custom.key", "value": {"stringValue": "custom-value"}},
        {"key": "numeric.key", "value": {"intValue": "42"}},
    ]
    payload = _make_otlp_payload(
        trace_id="trace-attrs",
        span_id="span-attrs",
        attributes=attrs,
    )
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 200

    db = await get_db()
    cursor = await db.execute(
        "SELECT attributes FROM telemetry_spans WHERE trace_id = ?",
        ("trace-attrs",),
    )
    row = await cursor.fetchone()
    parsed = json.loads(row["attributes"])
    assert parsed["custom.key"] == "custom-value"
    assert parsed["numeric.key"] == 42


# ---------------------------------------------------------------------------
# Test: Same trace_id reuses pipeline_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_trace_reuses_pipeline_run(client):
    """Two spans with the same trace_id should share one pipeline_run."""
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)

    for sid in ("span-reuse-1", "span-reuse-2"):
        payload = _make_otlp_payload(
            service_name="rfe-review",
            trace_id="trace-reuse",
            span_id=sid,
        )
        await client.post("/v1/traces", json=payload)

    db = await get_db()
    cursor = await db.execute(
        "SELECT DISTINCT pipeline_run_id FROM telemetry_spans WHERE trace_id = ?",
        ("trace-reuse",),
    )
    run_ids = await cursor.fetchall()
    assert len(run_ids) == 1
    assert run_ids[0][0] is not None


# ---------------------------------------------------------------------------
# Test: No telemetry summary for spans without token/cost attrs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_summary_without_token_attrs(client):
    """Spans without token/cost attributes should not create telemetry summaries."""
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)

    payload = _make_otlp_payload(
        service_name="rfe-review",
        trace_id="trace-no-tokens",
        span_id="span-no-tok",
        attributes=[
            {"key": "custom.key", "value": {"stringValue": "value"}},
        ],
    )
    await client.post("/v1/traces", json=payload)

    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM telemetry_summaries")
    count = (await cursor.fetchone())[0]
    assert count == 0
