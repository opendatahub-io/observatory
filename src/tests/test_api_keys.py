"""Tests for scoped API key management."""

import os
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _otlp_payload(service_name: str = "test-svc"):
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "api-key-trace-001",
                                "spanId": "api-key-span-001",
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def clean_client(tmp_path):
    """Client with no env var API key and a fresh database."""
    db_path = tmp_path / "test_api_keys.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)
    os.environ.pop("OBSERVATORY_API_KEY", None)

    import backend.config
    backend.config.settings = backend.config.Settings(
        database_path=db_path, api_key=""
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
    backend.config.settings = backend.config.Settings(database_path=db_path)


@pytest.fixture
async def env_key_client(tmp_path):
    """Client with OBSERVATORY_API_KEY env var set AND a fresh database."""
    db_path = tmp_path / "test_api_keys_env.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)
    os.environ["OBSERVATORY_API_KEY"] = "env-secret-key"

    import backend.config
    backend.config.settings = backend.config.Settings(
        database_path=db_path, api_key="env-secret-key"
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
    backend.config.settings = backend.config.Settings(database_path=db_path)


# ---------------------------------------------------------------------------
# Test: Create API key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_api_key(clean_client):
    """POST returns key with obs_ prefix."""
    resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "test-key", "scopes": ["*"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"].startswith("obs_")
    assert len(data["key"]) == 68  # "obs_" + 64 hex chars (256-bit entropy)
    assert data["key_prefix"] == data["key"][:12]
    assert data["name"] == "test-key"
    assert data["scopes"] == ["*"]
    assert data["id"] is not None


# ---------------------------------------------------------------------------
# Test: List API keys shows prefix, not full key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_api_keys_shows_prefix_not_full_key(clean_client):
    # Create a key first
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "list-test", "scopes": ["pipeline-a"]},
    )
    full_key = create_resp.json()["key"]

    resp = await clean_client.get("/api/admin/api-keys")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1

    # Find our key
    our_item = next(i for i in items if i["name"] == "list-test")
    assert our_item["key_prefix"] == full_key[:12]
    assert "key" not in our_item  # Full key must NOT be returned


# ---------------------------------------------------------------------------
# Test: Revoke API key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_api_key(clean_client):
    """DELETE then key returns 401."""
    # Create a key
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "revoke-test", "scopes": ["*"]},
    )
    data = create_resp.json()
    key_id = data["id"]
    full_key = data["key"]

    # Verify the key works for OTLP
    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload(),
        headers={"X-API-Key": full_key},
    )
    assert resp.status_code == 200

    # Revoke the key
    resp = await clean_client.delete(f"/api/admin/api-keys/{key_id}")
    assert resp.status_code == 204

    # Now the key should be rejected
    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload(),
        headers={"X-API-Key": full_key},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: Scoped key allows matching pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoped_key_allows_matching_pipeline(clean_client):
    """Create key scoped to ["rfe-review"], OTLP push with service.name=rfe-review succeeds."""
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "scoped-test", "scopes": ["rfe-review"]},
    )
    full_key = create_resp.json()["key"]

    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload("rfe-review"),
        headers={"X-API-Key": full_key},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Scoped key rejects wrong pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoped_key_rejects_wrong_pipeline(clean_client):
    """Same key, OTLP push with service.name=autofix-bugfix returns 403."""
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "wrong-scope-test", "scopes": ["rfe-review"]},
    )
    full_key = create_resp.json()["key"]

    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload("autofix-bugfix"),
        headers={"X-API-Key": full_key},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: Wildcard key allows any pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wildcard_key_allows_any_pipeline(clean_client):
    """Create ["*"] key, any pipeline succeeds."""
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "wildcard-test", "scopes": ["*"]},
    )
    full_key = create_resp.json()["key"]

    for svc in ["rfe-review", "autofix-bugfix", "random-pipeline"]:
        resp = await clean_client.post(
            "/v1/traces",
            json=_otlp_payload(svc),
            headers={"X-API-Key": full_key},
        )
        assert resp.status_code == 200, f"Failed for service.name={svc}"


# ---------------------------------------------------------------------------
# Test: Expired key returns 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_key_returns_401(clean_client):
    """An expired key should return 401."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "expired-test", "scopes": ["*"], "expires_at": past},
    )
    full_key = create_resp.json()["key"]

    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload(),
        headers={"X-API-Key": full_key},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: Env var fallback still works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_env_var_fallback_still_works(env_key_client):
    """OBSERVATORY_API_KEY env var works when no DB key matches."""
    resp = await env_key_client.post(
        "/v1/traces",
        json=_otlp_payload(),
        headers={"X-API-Key": "env-secret-key"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: No auth when no keys configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_auth_when_no_keys_configured(clean_client):
    """No DB keys + no env var = auth disabled."""
    resp = await clean_client.post(
        "/v1/traces",
        json=_otlp_payload(),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: last_used_at updated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_used_at_updated(clean_client):
    """After successful auth, last_used_at is set."""
    create_resp = await clean_client.post(
        "/api/admin/api-keys",
        json={"name": "last-used-test", "scopes": ["*"]},
    )
    data = create_resp.json()
    full_key = data["key"]
    key_id = data["id"]

    # Check that last_used_at is initially None
    list_resp = await clean_client.get("/api/admin/api-keys")
    our_key = next(k for k in list_resp.json() if k["id"] == key_id)
    assert our_key["last_used_at"] is None

    # Use the key
    await clean_client.post(
        "/v1/traces",
        json=_otlp_payload(),
        headers={"X-API-Key": full_key},
    )

    # Check that last_used_at is now set
    list_resp = await clean_client.get("/api/admin/api-keys")
    our_key = next(k for k in list_resp.json() if k["id"] == key_id)
    assert our_key["last_used_at"] is not None
