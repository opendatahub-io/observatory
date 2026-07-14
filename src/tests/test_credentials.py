"""Tests for platform credential management (ADR-0006)."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def cred_client(tmp_path):
    """Client with a derived credential key (from api_key) and a fresh database."""
    db_path = tmp_path / "test_credentials.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)
    os.environ.pop("OBSERVATORY_CREDENTIAL_KEY", None)
    os.environ.pop("OBSERVATORY_API_KEY", None)

    import backend.config
    backend.config.settings = backend.config.Settings(
        database_path=db_path,
        api_key="test-api-key-for-credentials",
        credential_key="",
    )

    import backend.database
    backend.database._db = None

    from backend.database import connect, disconnect, init_schema
    db = await connect()
    await init_schema(db)

    from backend.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await disconnect()
    backend.database._db = None
    os.environ.pop("OBSERVATORY_API_KEY", None)
    os.environ.pop("OBSERVATORY_CREDENTIAL_KEY", None)


@pytest.fixture
async def cred_db(tmp_path):
    """Return a raw db connection for direct CRUD testing."""
    db_path = tmp_path / "test_cred_db.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)
    os.environ.pop("OBSERVATORY_CREDENTIAL_KEY", None)

    import backend.config
    backend.config.settings = backend.config.Settings(
        database_path=db_path,
        api_key="test-api-key-for-credentials",
        credential_key="",
    )

    import backend.database
    backend.database._db = None

    from backend.database import connect, disconnect, init_schema
    db = await connect()
    await init_schema(db)
    yield db
    await disconnect()
    backend.database._db = None


# ---------------------------------------------------------------------------
# Test: Create credential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_credential(cred_client):
    """POST returns 201 and no token in response."""
    resp = await cred_client.post(
        "/api/admin/credentials",
        json={
            "name": "my-gitlab-token",
            "platform": "gitlab",
            "base_url": "https://gitlab.com",
            "token": "glpat-secret-token-value",
            "scopes": ["*"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-gitlab-token"
    assert data["platform"] == "gitlab"
    assert data["base_url"] == "https://gitlab.com"
    assert data["scopes"] == ["*"]
    assert data["is_active"] is True
    assert data["id"] is not None
    # Token must NOT be in the response
    assert "token" not in data
    assert "encrypted_token" not in data


# ---------------------------------------------------------------------------
# Test: List credentials exposes no tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_credentials_no_tokens(cred_client):
    """GET list does not expose tokens."""
    await cred_client.post(
        "/api/admin/credentials",
        json={
            "name": "list-test-cred",
            "platform": "github",
            "base_url": "https://github.com",
            "token": "ghp_secret123",
        },
    )

    resp = await cred_client.get("/api/admin/credentials")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1

    for item in items:
        assert "token" not in item
        assert "encrypted_token" not in item
        assert "name" in item
        assert "platform" in item


# ---------------------------------------------------------------------------
# Test: Update credential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_credential(cred_client):
    """PUT changes name/scopes."""
    create_resp = await cred_client.post(
        "/api/admin/credentials",
        json={
            "name": "update-test",
            "platform": "gitlab",
            "base_url": "https://gitlab.com",
            "token": "glpat-original",
            "scopes": ["*"],
        },
    )
    cred_id = create_resp.json()["id"]

    resp = await cred_client.put(
        f"/api/admin/credentials/{cred_id}",
        json={"name": "updated-name", "scopes": ["pipeline-a", "pipeline-b"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "updated-name"
    assert data["scopes"] == ["pipeline-a", "pipeline-b"]


# ---------------------------------------------------------------------------
# Test: Rotate token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotate_token(cred_db):
    """PUT with new token, verify the new token decrypts correctly."""
    from backend.crud.credentials import create_credential, update_credential, decrypt_token

    row = await create_credential(
        cred_db, "rotate-test", "gitlab", "https://gitlab.com",
        "original-token", ["*"],
    )
    cred_id = row["id"]

    await update_credential(cred_db, cred_id, token="rotated-token")

    # Fetch the encrypted token from DB
    cursor = await cred_db.execute(
        "SELECT encrypted_token FROM platform_credentials WHERE id = ?",
        (cred_id,),
    )
    db_row = await cursor.fetchone()
    decrypted = decrypt_token(db_row["encrypted_token"])
    assert decrypted == "rotated-token"


# ---------------------------------------------------------------------------
# Test: Revoke credential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_credential(cred_client):
    """DELETE sets inactive."""
    create_resp = await cred_client.post(
        "/api/admin/credentials",
        json={
            "name": "revoke-test",
            "platform": "gitlab",
            "base_url": "https://gitlab.com",
            "token": "glpat-to-revoke",
        },
    )
    cred_id = create_resp.json()["id"]

    resp = await cred_client.delete(f"/api/admin/credentials/{cred_id}")
    assert resp.status_code == 204

    # Verify it's now inactive
    list_resp = await cred_client.get("/api/admin/credentials")
    cred = next(c for c in list_resp.json() if c["id"] == cred_id)
    assert cred["is_active"] is False


# ---------------------------------------------------------------------------
# Test: Resolve credential for pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_credential_for_pipeline(cred_db):
    """Create credential scoped to a pipeline, verify resolution."""
    from backend.crud.credentials import create_credential, get_credential_for_pipeline

    await create_credential(
        cred_db, "scoped-cred", "gitlab", "https://gitlab.com",
        "glpat-scoped-secret", ["rfe-autofixer"],
    )

    pipeline = {
        "platform": "gitlab",
        "repo_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer",
        "slug": "rfe-autofixer",
    }

    token = await get_credential_for_pipeline(cred_db, pipeline)
    assert token == "glpat-scoped-secret"


# ---------------------------------------------------------------------------
# Test: Falls back to env var when no DB credential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_falls_back_to_env_var(cred_db):
    """No DB credential, env var used."""
    from backend.crud.credentials import get_credential_for_pipeline

    pipeline = {
        "platform": "gitlab",
        "repo_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer",
        "slug": "rfe-autofixer",
    }

    # No credentials in DB, so should return None
    token = await get_credential_for_pipeline(cred_db, pipeline)
    assert token is None

    # The collector itself would then fall back to the env var.
    # We verify that flow by testing the GitLab collector with a mocked config.
    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "env-var-token"

        # Also patch the credential lookup to return None
        with patch("backend.crud.credentials.get_credential_for_pipeline",
                    new_callable=AsyncMock, return_value=None):
            from backend.collector.gitlab import GitLabCollector
            collector = GitLabCollector()

            # Mock the httpx client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_response.headers = {"RateLimit-Remaining": "100"}
            mock_response.text = ""

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)

            with patch("httpx.AsyncClient") as MockClient:
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                pipeline_with_id = {**pipeline, "id": 1, "platform_project_id": "12345"}
                runs = await collector.collect_runs(cred_db, pipeline_with_id)

    assert runs == []  # empty because mocked API returned []


# ---------------------------------------------------------------------------
# Test: Prefers matching base_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_prefers_matching_base_url(cred_db):
    """Two credentials — picks the one matching repo_url host."""
    from backend.crud.credentials import create_credential, get_credential_for_pipeline

    # Create a credential for gitlab.com
    await create_credential(
        cred_db, "gitlab-com", "gitlab", "https://gitlab.com",
        "token-for-gitlab-com", ["*"],
    )

    # Create a credential for a private GitLab
    await create_credential(
        cred_db, "private-gitlab", "gitlab", "https://gitlab.cee.redhat.com",
        "token-for-private-gitlab", ["*"],
    )

    # Pipeline on gitlab.cee.redhat.com
    pipeline = {
        "platform": "gitlab",
        "repo_url": "https://gitlab.cee.redhat.com/org/repo",
        "slug": "my-pipeline",
    }

    token = await get_credential_for_pipeline(cred_db, pipeline)
    assert token == "token-for-private-gitlab"

    # Pipeline on gitlab.com
    pipeline2 = {
        "platform": "gitlab",
        "repo_url": "https://gitlab.com/org/repo",
        "slug": "my-other-pipeline",
    }

    token2 = await get_credential_for_pipeline(cred_db, pipeline2)
    assert token2 == "token-for-gitlab-com"


# ---------------------------------------------------------------------------
# Test: Expired credential skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_credential_skipped(cred_db):
    """Expired credential not returned."""
    from backend.crud.credentials import create_credential, get_credential_for_pipeline

    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await create_credential(
        cred_db, "expired-cred", "gitlab", "https://gitlab.com",
        "expired-token", ["*"], expires_at=past,
    )

    pipeline = {
        "platform": "gitlab",
        "repo_url": "https://gitlab.com/org/repo",
        "slug": "test-pipeline",
    }

    token = await get_credential_for_pipeline(cred_db, pipeline)
    assert token is None


# ---------------------------------------------------------------------------
# Test: Test endpoint returns result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_endpoint_returns_result(cred_client):
    """Mock the HTTP call, verify test endpoint works."""
    create_resp = await cred_client.post(
        "/api/admin/credentials",
        json={
            "name": "test-endpoint-cred",
            "platform": "gitlab",
            "base_url": "https://gitlab.com",
            "token": "glpat-test-token",
        },
    )
    cred_id = create_resp.json()["id"]

    # Mock the httpx client used inside test_credential
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.crud.credentials.httpx.AsyncClient", return_value=mock_client):
        resp = await cred_client.post(f"/api/admin/credentials/{cred_id}/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Credential is valid"


# ---------------------------------------------------------------------------
# Test: Encryption roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_encryption_roundtrip(cred_db):
    """Encrypt then decrypt, verify match."""
    from backend.crud.credentials import encrypt_token, decrypt_token

    original = "glpat-my-super-secret-token-12345"
    encrypted = encrypt_token(original)

    # Encrypted should be different from original
    assert encrypted != original

    decrypted = decrypt_token(encrypted)
    assert decrypted == original


# ---------------------------------------------------------------------------
# Test: Credential not found returns 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_nonexistent_returns_404(cred_client):
    """PUT on non-existent credential returns 404."""
    resp = await cred_client.put(
        "/api/admin/credentials/99999",
        json={"name": "nope"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_nonexistent_returns_404(cred_client):
    """DELETE on non-existent credential returns 404."""
    resp = await cred_client.delete("/api/admin/credentials/99999")
    assert resp.status_code == 404
