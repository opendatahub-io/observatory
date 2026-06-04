import pytest


SAMPLE_PIPELINE = {
    "slug": "prov-test",
    "name": "Provenance Test Pipeline",
    "description": "Pipeline for testing provenance",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/prov",
    "platform": "github",
}

SAMPLE_PIPELINE_B = {
    "slug": "prov-test-b",
    "name": "Provenance Test Pipeline B",
    "description": "Second pipeline for cross-pipeline tests",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/prov-b",
    "platform": "github",
}


@pytest.fixture
async def provenance_data(client):
    """Create a pipeline, a run, and insert provenance records."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()

    # Create a run
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status, started_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, pipeline_id, "ext-100", "success", "2026-06-01T00:00:00"),
    )

    # Insert commands
    await db.execute(
        "INSERT INTO run_commands (pipeline_run_id, step_order, command, exit_code, duration_ms, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (100, 1, "pip install -r requirements.txt", 0, 5000, "manifest"),
    )
    await db.execute(
        "INSERT INTO run_commands (pipeline_run_id, step_order, command, exit_code, duration_ms, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (100, 2, "pytest tests/", 0, 12000, "manifest"),
    )

    # Insert packages
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, "pip", "requests", "2.31.0", "manifest"),
    )
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, "pip", "flask", "3.0.0", "manifest"),
    )
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, "npm", "express", "4.18.2", "manifest"),
    )

    # Insert containers
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, "python:3.11", "sha256:abc123", "linux/amd64", "manifest"),
    )
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (100, "redis:7", "sha256:def456", "linux/amd64", "manifest"),
    )

    await db.commit()
    return {"pipeline_id": pipeline_id, "run_id": 100}


@pytest.fixture
async def cross_pipeline_data(client, provenance_data):
    """Create a second pipeline with its own run and provenance."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE_B)
    assert resp.status_code == 201
    pipeline_b_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()

    # Create a run for pipeline B
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status, started_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (200, pipeline_b_id, "ext-200", "success", "2026-06-01T00:00:00"),
    )

    # Shared package (requests, same manager, different version)
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (200, "pip", "requests", "2.32.0", "manifest"),
    )

    # Unique package for pipeline B
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (200, "pip", "django", "5.0.0", "manifest"),
    )

    # Shared container (python:3.11) + unique container
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (200, "python:3.11", "sha256:abc123", "linux/amd64", "manifest"),
    )
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (200, "postgres:16", "sha256:ghi789", "linux/amd64", "manifest"),
    )

    await db.commit()
    return provenance_data


# -- Full provenance endpoint --


@pytest.mark.asyncio
async def test_full_provenance(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(f"/api/pipelines/prov-test/runs/{run_id}/provenance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert len(body["commands"]) == 2
    assert len(body["packages"]) == 3
    assert len(body["containers"]) == 2


# -- Commands endpoint --


@pytest.mark.asyncio
async def test_commands(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(f"/api/pipelines/prov-test/runs/{run_id}/commands")
    assert resp.status_code == 200
    commands = resp.json()
    assert len(commands) == 2
    assert commands[0]["step_order"] == 1
    assert commands[0]["command"] == "pip install -r requirements.txt"
    assert commands[1]["step_order"] == 2
    assert commands[1]["command"] == "pytest tests/"


# -- Packages endpoint --


@pytest.mark.asyncio
async def test_packages(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(f"/api/pipelines/prov-test/runs/{run_id}/packages")
    assert resp.status_code == 200
    packages = resp.json()
    assert len(packages) == 3


@pytest.mark.asyncio
async def test_packages_filter_manager(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(
        f"/api/pipelines/prov-test/runs/{run_id}/packages?manager=pip"
    )
    assert resp.status_code == 200
    packages = resp.json()
    assert len(packages) == 2
    for pkg in packages:
        assert pkg["manager"] == "pip"


@pytest.mark.asyncio
async def test_packages_filter_manager_npm(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(
        f"/api/pipelines/prov-test/runs/{run_id}/packages?manager=npm"
    )
    assert resp.status_code == 200
    packages = resp.json()
    assert len(packages) == 1
    assert packages[0]["name"] == "express"


# -- Containers endpoint --


@pytest.mark.asyncio
async def test_containers(client, provenance_data):
    run_id = provenance_data["run_id"]
    resp = await client.get(f"/api/pipelines/prov-test/runs/{run_id}/containers")
    assert resp.status_code == 200
    containers = resp.json()
    assert len(containers) == 2
    refs = [c["image_ref"] for c in containers]
    assert "python:3.11" in refs
    assert "redis:7" in refs


# -- Cross-pipeline package inventory --


@pytest.mark.asyncio
async def test_package_inventory(client, cross_pipeline_data):
    resp = await client.get("/api/provenance/packages")
    assert resp.status_code == 200
    body = resp.json()
    packages = body["packages"]

    # Find the shared 'requests' package
    requests_pkg = [p for p in packages if p["name"] == "requests"]
    assert len(requests_pkg) == 1
    assert set(requests_pkg[0]["pipelines"]) == {"prov-test", "prov-test-b"}
    assert set(requests_pkg[0]["versions"]) == {"2.31.0", "2.32.0"}

    # django should only be in prov-test-b
    django_pkg = [p for p in packages if p["name"] == "django"]
    assert len(django_pkg) == 1
    assert django_pkg[0]["pipelines"] == ["prov-test-b"]


# -- Cross-pipeline container inventory --


@pytest.mark.asyncio
async def test_container_inventory(client, cross_pipeline_data):
    resp = await client.get("/api/provenance/containers")
    assert resp.status_code == 200
    body = resp.json()
    containers = body["containers"]

    # python:3.11 should be in both pipelines
    python_img = [c for c in containers if c["image_ref"] == "python:3.11"]
    assert len(python_img) == 1
    assert set(python_img[0]["pipelines"]) == {"prov-test", "prov-test-b"}

    # postgres:16 should only be in prov-test-b
    postgres_img = [c for c in containers if c["image_ref"] == "postgres:16"]
    assert len(postgres_img) == 1
    assert postgres_img[0]["pipelines"] == ["prov-test-b"]


# -- 404 cases --


@pytest.mark.asyncio
async def test_provenance_pipeline_not_found(client):
    resp = await client.get("/api/pipelines/nonexistent/runs/1/provenance")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_provenance_run_not_found(client, provenance_data):
    resp = await client.get("/api/pipelines/prov-test/runs/99999/provenance")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_commands_pipeline_not_found(client):
    resp = await client.get("/api/pipelines/nonexistent/runs/1/commands")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_commands_run_not_found(client, provenance_data):
    resp = await client.get("/api/pipelines/prov-test/runs/99999/commands")
    assert resp.status_code == 404


# -- Empty provenance --


@pytest.mark.asyncio
async def test_empty_provenance(client):
    """A run with no provenance data returns empty arrays."""
    resp = await client.post("/api/pipelines", json={
        "slug": "empty-prov",
        "name": "Empty Provenance Pipeline",
        "repo_url": "https://github.com/example/empty",
        "platform": "github",
    })
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) "
        "VALUES (?, ?, ?, ?)",
        (300, pipeline_id, "ext-300", "success"),
    )
    await db.commit()

    resp = await client.get("/api/pipelines/empty-prov/runs/300/provenance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == 300
    assert body["commands"] == []
    assert body["packages"] == []
    assert body["containers"] == []


@pytest.mark.asyncio
async def test_empty_commands(client):
    """A run with no commands returns an empty list."""
    resp = await client.post("/api/pipelines", json={
        "slug": "empty-cmd",
        "name": "Empty Commands Pipeline",
        "repo_url": "https://github.com/example/empty-cmd",
        "platform": "github",
    })
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) "
        "VALUES (?, ?, ?, ?)",
        (301, pipeline_id, "ext-301", "success"),
    )
    await db.commit()

    resp = await client.get("/api/pipelines/empty-cmd/runs/301/commands")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_empty_package_inventory(client):
    """Package inventory with no data returns empty list."""
    resp = await client.get("/api/provenance/packages")
    assert resp.status_code == 200
    assert resp.json() == {"packages": []}


@pytest.mark.asyncio
async def test_empty_container_inventory(client):
    """Container inventory with no data returns empty list."""
    resp = await client.get("/api/provenance/containers")
    assert resp.status_code == 200
    assert resp.json() == {"containers": []}
