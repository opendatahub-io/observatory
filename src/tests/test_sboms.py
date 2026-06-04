import pytest


SAMPLE_SBOM_PAYLOAD = {
    "image_digest": "sha256:abc123def456",
    "image_ref": "quay.io/myorg/myimage:latest",
    "format": "spdx-json",
    "sbom": {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "name": "myimage",
        "packages": [
            {"name": "openssl", "versionInfo": "3.1.0"},
            {"name": "glibc", "versionInfo": "2.37"},
        ],
    },
    "generator": "syft",
    "generated_at": "2026-06-01T12:00:00",
}


# -- Push SBOM (POST) --


@pytest.mark.asyncio
async def test_push_sbom_returns_201(client):
    resp = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["image_digest"] == SAMPLE_SBOM_PAYLOAD["image_digest"]
    assert body["image_ref"] == SAMPLE_SBOM_PAYLOAD["image_ref"]
    assert body["format"] == "spdx-json"
    assert body["generator"] == "syft"
    assert body["sbom"]["spdxVersion"] == "SPDX-2.3"
    assert "id" in body


# -- List SBOMs (GET) --


@pytest.mark.asyncio
async def test_list_sboms(client):
    # Push first
    await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)

    resp = await client.get("/api/sboms")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    item = items[0]
    assert item["image_digest"] == SAMPLE_SBOM_PAYLOAD["image_digest"]
    assert item["image_ref"] == SAMPLE_SBOM_PAYLOAD["image_ref"]
    # List endpoint should NOT include the full sbom content
    assert "sbom" not in item


# -- Get SBOM by digest --


@pytest.mark.asyncio
async def test_get_sbom_by_digest(client):
    await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)

    digest = SAMPLE_SBOM_PAYLOAD["image_digest"]
    resp = await client.get(f"/api/sboms/{digest}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["image_digest"] == digest
    assert body["sbom"]["spdxVersion"] == "SPDX-2.3"
    assert len(body["sbom"]["packages"]) == 2


@pytest.mark.asyncio
async def test_get_sbom_not_found(client):
    resp = await client.get("/api/sboms/sha256:nonexistent")
    assert resp.status_code == 404


# -- Upsert (push same digest again) --


@pytest.mark.asyncio
async def test_upsert_sbom_no_duplicate(client):
    # Push once
    resp1 = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    assert resp1.status_code == 201

    # Push again with updated image_ref
    updated = {**SAMPLE_SBOM_PAYLOAD, "image_ref": "quay.io/myorg/myimage:v2"}
    resp2 = await client.post("/api/sboms", json=updated)
    assert resp2.status_code == 201
    assert resp2.json()["image_ref"] == "quay.io/myorg/myimage:v2"

    # List should still have exactly one entry for this digest
    resp3 = await client.get("/api/sboms")
    assert resp3.status_code == 200
    items = resp3.json()
    matching = [
        i for i in items
        if i["image_digest"] == SAMPLE_SBOM_PAYLOAD["image_digest"]
    ]
    assert len(matching) == 1


# -- Vulnerabilities (empty initially) --


@pytest.mark.asyncio
async def test_vulnerabilities_empty(client):
    await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    digest = SAMPLE_SBOM_PAYLOAD["image_digest"]

    resp = await client.get(f"/api/sboms/{digest}/vulnerabilities")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_vulnerabilities_not_found_sbom(client):
    resp = await client.get("/api/sboms/sha256:nonexistent/vulnerabilities")
    assert resp.status_code == 404


# -- Vulnerabilities (with data) --


@pytest.mark.asyncio
async def test_vulnerabilities_with_data(client):
    # Push an SBOM
    resp = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    assert resp.status_code == 201
    sbom_id = resp.json()["id"]

    # Insert vulnerability data directly
    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, installed_version, fixed_version, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sbom_id, "CVE-2024-1234", "openssl", "3.1.0", "3.1.1", "HIGH"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, installed_version, fixed_version, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sbom_id, "CVE-2024-5678", "glibc", "2.37", "2.38", "CRITICAL"),
    )
    await db.commit()

    digest = SAMPLE_SBOM_PAYLOAD["image_digest"]
    resp = await client.get(f"/api/sboms/{digest}/vulnerabilities")
    assert resp.status_code == 200
    vulns = resp.json()
    assert len(vulns) == 2
    vuln_ids = {v["vuln_id"] for v in vulns}
    assert "CVE-2024-1234" in vuln_ids
    assert "CVE-2024-5678" in vuln_ids
    assert vulns[0]["sbom_id"] == sbom_id


# -- Vulnerability summary endpoint --


@pytest.mark.asyncio
async def test_vulnerability_summary(client):
    # Push two SBOMs
    resp1 = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    sbom1_id = resp1.json()["id"]

    sbom2_payload = {
        "image_digest": "sha256:second999",
        "image_ref": "quay.io/other/image:latest",
        "format": "spdx-json",
        "sbom": {"spdxVersion": "SPDX-2.3", "packages": []},
        "generator": "trivy",
    }
    resp2 = await client.post("/api/sboms", json=sbom2_payload)
    sbom2_id = resp2.json()["id"]

    # Insert vulnerabilities
    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, installed_version, fixed_version, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sbom1_id, "CVE-2024-1111", "openssl", "3.1.0", "3.1.1", "HIGH"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, installed_version, fixed_version, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sbom2_id, "CVE-2024-2222", "curl", "8.0.0", "8.0.1", "MEDIUM"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, installed_version, fixed_version, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sbom2_id, "CVE-2024-3333", "zlib", "1.2.13", "1.3.0", "HIGH"),
    )
    await db.commit()

    # Get all vulnerabilities
    resp = await client.get("/api/provenance/vulnerabilities")
    assert resp.status_code == 200
    vulns = resp.json()
    assert len(vulns) == 3

    # Each entry should have image_digest and image_ref from the join
    for v in vulns:
        assert "image_digest" in v
        assert "image_ref" in v
        assert "vuln_id" in v


@pytest.mark.asyncio
async def test_vulnerability_summary_filter_severity(client):
    # Push SBOM and insert vulns
    resp = await client.post("/api/sboms", json=SAMPLE_SBOM_PAYLOAD)
    sbom_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, severity) "
        "VALUES (?, ?, ?, ?)",
        (sbom_id, "CVE-2024-9001", "pkg-a", "CRITICAL"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, severity) "
        "VALUES (?, ?, ?, ?)",
        (sbom_id, "CVE-2024-9002", "pkg-b", "LOW"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities "
        "(sbom_id, vuln_id, package_name, severity) "
        "VALUES (?, ?, ?, ?)",
        (sbom_id, "CVE-2024-9003", "pkg-c", "CRITICAL"),
    )
    await db.commit()

    # Filter by CRITICAL
    resp = await client.get("/api/provenance/vulnerabilities?severity=CRITICAL")
    assert resp.status_code == 200
    vulns = resp.json()
    assert len(vulns) == 2
    for v in vulns:
        assert v["severity"] == "CRITICAL"

    # Filter by LOW
    resp = await client.get("/api/provenance/vulnerabilities?severity=LOW")
    assert resp.status_code == 200
    vulns = resp.json()
    assert len(vulns) == 1
    assert vulns[0]["vuln_id"] == "CVE-2024-9002"

    # Filter by non-existent severity
    resp = await client.get("/api/provenance/vulnerabilities?severity=EXTREME")
    assert resp.status_code == 200
    assert resp.json() == []
