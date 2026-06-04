import pytest


SAMPLE_PIPELINE = {
    "slug": "my-pipeline",
    "name": "My Pipeline",
    "description": "A test pipeline",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/repo",
    "platform": "github",
}


@pytest.mark.asyncio
async def test_create_pipeline(client):
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "my-pipeline"
    assert body["name"] == "My Pipeline"
    assert body["repo_url"] == "https://github.com/example/repo"
    assert body["platform"] == "github"
    assert body["health"] == "grey"
    assert body["id"] is not None
    assert body["status"] == "production"


@pytest.mark.asyncio
async def test_list_pipelines(client):
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    resp = await client.get("/api/pipelines")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pipelines"]) == 1
    assert body["pipelines"][0]["slug"] == "my-pipeline"
    assert body["pipelines"][0]["health"] == "grey"


@pytest.mark.asyncio
async def test_get_pipeline(client):
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    resp = await client.get("/api/pipelines/my-pipeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "my-pipeline"
    assert body["name"] == "My Pipeline"
    assert body["description"] == "A test pipeline"
    assert body["owner"] == "team-qa"
    assert body["repo_url"] == "https://github.com/example/repo"
    assert body["platform"] == "github"
    assert body["health"] == "grey"


@pytest.mark.asyncio
async def test_get_pipeline_not_found(client):
    resp = await client.get("/api/pipelines/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_pipeline(client):
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    resp = await client.put(
        "/api/pipelines/my-pipeline",
        json={"name": "Updated Pipeline"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Updated Pipeline"
    assert body["slug"] == "my-pipeline"


@pytest.mark.asyncio
async def test_delete_pipeline(client):
    await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    resp = await client.delete("/api/pipelines/my-pipeline")
    assert resp.status_code == 204
    resp = await client.get("/api/pipelines/my-pipeline")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_slug(client):
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 409
