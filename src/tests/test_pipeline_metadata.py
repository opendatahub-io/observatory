import pytest


SAMPLE_PIPELINE = {
    "slug": "meta-test",
    "name": "Metadata Test Pipeline",
    "repo_url": "https://github.com/example/repo",
    "platform": "github",
}


async def _create_pipeline(client):
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    return resp.json()


# ---------- Skills ----------

@pytest.mark.asyncio
async def test_create_and_list_skills(client):
    await _create_pipeline(client)

    # Create a skill
    resp = await client.post(
        "/api/pipelines/meta-test/skills",
        json={"repo_url": "https://github.com/org/skill-repo", "branch": "main", "purpose": "testing"},
    )
    assert resp.status_code == 201
    skill = resp.json()
    assert skill["repo_url"] == "https://github.com/org/skill-repo"
    assert skill["branch"] == "main"
    assert skill["purpose"] == "testing"
    assert skill["pipeline_id"] is not None

    # List skills
    resp = await client.get("/api/pipelines/meta-test/skills")
    assert resp.status_code == 200
    skills = resp.json()
    assert len(skills) == 1
    assert skills[0]["repo_url"] == "https://github.com/org/skill-repo"


# ---------- Jira Contracts ----------

@pytest.mark.asyncio
async def test_create_jira_contract_with_labels(client):
    await _create_pipeline(client)

    resp = await client.post(
        "/api/pipelines/meta-test/jira-contracts",
        json={"project": "RHEL", "labels_applied": ["ci", "nightly", "agentic"]},
    )
    assert resp.status_code == 201
    contract = resp.json()
    assert contract["project"] == "RHEL"
    assert contract["labels_applied"] == ["ci", "nightly", "agentic"]

    # List and verify labels come back as a list
    resp = await client.get("/api/pipelines/meta-test/jira-contracts")
    assert resp.status_code == 200
    contracts = resp.json()
    assert len(contracts) == 1
    assert contracts[0]["labels_applied"] == ["ci", "nightly", "agentic"]


@pytest.mark.asyncio
async def test_create_jira_contract_null_labels(client):
    await _create_pipeline(client)

    resp = await client.post(
        "/api/pipelines/meta-test/jira-contracts",
        json={"project": "AAH"},
    )
    assert resp.status_code == 201
    contract = resp.json()
    assert contract["project"] == "AAH"
    assert contract["labels_applied"] is None


# ---------- Pipeline detail includes metadata ----------

@pytest.mark.asyncio
async def test_pipeline_detail_includes_metadata(client):
    await _create_pipeline(client)

    # Add an image and a skill
    await client.post(
        "/api/pipelines/meta-test/images",
        json={"name": "ubi8", "ref": "registry.access.redhat.com/ubi8:latest"},
    )
    await client.post(
        "/api/pipelines/meta-test/skills",
        json={"repo_url": "https://github.com/org/skill", "purpose": "build"},
    )

    resp = await client.get("/api/pipelines/meta-test")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["images"]) == 1
    assert body["images"][0]["name"] == "ubi8"
    assert body["images"][0]["ref"] == "registry.access.redhat.com/ubi8:latest"

    assert len(body["skills"]) == 1
    assert body["skills"][0]["repo_url"] == "https://github.com/org/skill"

    assert body["shared_libs"] == []
    assert body["jira_contracts"] == []
    assert body["telemetry_config"] == []
    assert body["artifact_config"] == []


# ---------- Delete sub-resource ----------

@pytest.mark.asyncio
async def test_delete_sub_resource(client):
    await _create_pipeline(client)

    # Create an image
    resp = await client.post(
        "/api/pipelines/meta-test/images",
        json={"name": "centos", "ref": "quay.io/centos/centos:stream9"},
    )
    assert resp.status_code == 201
    image_id = resp.json()["id"]

    # Verify it exists
    resp = await client.get("/api/pipelines/meta-test/images")
    assert len(resp.json()) == 1

    # Delete it
    resp = await client.delete(f"/api/pipelines/meta-test/images/{image_id}")
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get("/api/pipelines/meta-test/images")
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_sub_resource(client):
    await _create_pipeline(client)
    resp = await client.delete("/api/pipelines/meta-test/images/9999")
    assert resp.status_code == 404


# ---------- Nonexistent pipeline returns 404 ----------

@pytest.mark.asyncio
async def test_metadata_on_nonexistent_pipeline(client):
    resp = await client.get("/api/pipelines/does-not-exist/skills")
    assert resp.status_code == 404

    resp = await client.post(
        "/api/pipelines/does-not-exist/skills",
        json={"repo_url": "https://github.com/org/repo"},
    )
    assert resp.status_code == 404

    resp = await client.delete("/api/pipelines/does-not-exist/images/1")
    assert resp.status_code == 404


# ---------- Other sub-resources ----------

@pytest.mark.asyncio
async def test_shared_libs_crud(client):
    await _create_pipeline(client)

    resp = await client.post(
        "/api/pipelines/meta-test/shared-libs",
        json={"repo_url": "https://github.com/org/shared-lib", "purpose": "utilities"},
    )
    assert resp.status_code == 201
    assert resp.json()["repo_url"] == "https://github.com/org/shared-lib"

    resp = await client.get("/api/pipelines/meta-test/shared-libs")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_telemetry_config_crud(client):
    await _create_pipeline(client)

    resp = await client.post(
        "/api/pipelines/meta-test/telemetry-config",
        json={"collector_type": "otel", "endpoint": "https://otel.example.com"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["collector_type"] == "otel"
    assert body["status"] == "active"

    resp = await client.get("/api/pipelines/meta-test/telemetry-config")
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_artifact_config_crud(client):
    await _create_pipeline(client)

    resp = await client.post(
        "/api/pipelines/meta-test/artifact-config",
        json={"results_repo": "https://github.com/org/results"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["results_repo"] == "https://github.com/org/results"
    assert body["status"] == "active"

    resp = await client.get("/api/pipelines/meta-test/artifact-config")
    assert len(resp.json()) == 1
