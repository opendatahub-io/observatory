"""Tests for API key authentication on push endpoints."""

import os

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_OTLP_PAYLOAD = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "test-svc"}}
                ]
            },
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "auth-trace-001",
                            "spanId": "auth-span-001",
                            "name": "test.op",
                            "startTimeUnixNano": "1716883200000000000",
                            "endTimeUnixNano": "1716886800000000000",
                            "status": {"code": 1},
                        }
                    ]
                }
            ],
        }
    ]
}

SAMPLE_SBOM_PAYLOAD = {
    "image_digest": "sha256:authtest123",
    "image_ref": "quay.io/test/image:latest",
    "format": "spdx-json",
    "sbom": {"spdxVersion": "SPDX-2.3", "packages": []},
    "generator": "test",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_with_api_key(tmp_path):
    """Client fixture where an API key is configured."""
    db_path = tmp_path / "test_auth.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)
    os.environ["OBSERVATORY_API_KEY"] = "test-secret-key-123"

    import backend.config
    backend.config.settings = backend.config.Settings(
        database_path=db_path, api_key="test-secret-key-123"
    )

    import backend.database
    backend.database._db = None

    from backend.database import connect, disconnect, init_schema
    db = await connect()
    await init_schema(db)

    from backend.app import app
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await disconnect()
    backend.database._db = None
    os.environ.pop("OBSERVATORY_API_KEY", None)
    # Reset settings to default (no api key)
    backend.config.settings = backend.config.Settings(database_path=db_path)


# ---------------------------------------------------------------------------
# Test: Push endpoint returns 401 without API key when key is configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otlp_rejects_without_key(client_with_api_key):
    resp = await client_with_api_key.post("/v1/traces", json=SAMPLE_OTLP_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mlflow_create_experiment_rejects_without_key(client_with_api_key):
    resp = await client_with_api_key.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "no-auth-exp"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sbom_push_rejects_without_key(client_with_api_key):
    resp = await client_with_api_key.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: Push endpoint returns 200 with correct API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otlp_accepts_with_correct_key(client_with_api_key):
    resp = await client_with_api_key.post(
        "/v1/traces",
        json=SAMPLE_OTLP_PAYLOAD,
        headers={"X-API-Key": "test-secret-key-123"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mlflow_create_experiment_accepts_with_correct_key(client_with_api_key):
    resp = await client_with_api_key.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "auth-exp"},
        headers={"X-API-Key": "test-secret-key-123"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sbom_push_accepts_with_correct_key(client_with_api_key):
    resp = await client_with_api_key.post(
        "/api/sboms",
        json=SAMPLE_SBOM_PAYLOAD,
        headers={"X-API-Key": "test-secret-key-123"},
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Test: Push endpoint returns 401 with wrong API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otlp_rejects_wrong_key(client_with_api_key):
    resp = await client_with_api_key.post(
        "/v1/traces",
        json=SAMPLE_OTLP_PAYLOAD,
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: Push endpoints work without auth when no key is configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otlp_works_without_auth_when_no_key_configured(client):
    """When OBSERVATORY_API_KEY is empty, push endpoints should work without auth."""
    resp = await client.post("/v1/traces", json=SAMPLE_OTLP_PAYLOAD)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mlflow_works_without_auth_when_no_key_configured(client):
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "no-key-exp"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sbom_works_without_auth_when_no_key_configured(client):
    resp = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Test: Read endpoints work without API key even when key is configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz_open_with_key_configured(client_with_api_key):
    resp = await client_with_api_key.get("/healthz")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mlflow_search_experiments_open_with_key_configured(client_with_api_key):
    resp = await client_with_api_key.get("/mlflow/api/2.0/mlflow/experiments/search")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sbom_list_open_with_key_configured(client_with_api_key):
    resp = await client_with_api_key.get("/api/sboms")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_telemetry_spans_open_with_key_configured(client_with_api_key):
    resp = await client_with_api_key.get("/api/telemetry/spans/1")
    assert resp.status_code == 200
