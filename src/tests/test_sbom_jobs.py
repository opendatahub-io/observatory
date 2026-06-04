"""Tests for SBOM generation and vulnerability scanning background jobs."""

import json

import pytest
from unittest.mock import AsyncMock, patch


SAMPLE_SPDX_SBOM = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "python:3.11",
    "packages": [
        {
            "SPDXID": "SPDXRef-Package-pip-requests-2.31.0",
            "name": "requests",
            "versionInfo": "2.31.0",
        }
    ],
}

SAMPLE_GRYPE_OUTPUT = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2024-1234",
                "severity": "High",
                "fix": {
                    "versions": ["2.32.0"],
                    "state": "fixed",
                },
            },
            "artifact": {
                "name": "requests",
                "version": "2.31.0",
            },
        },
        {
            "vulnerability": {
                "id": "CVE-2024-5678",
                "severity": "Medium",
                "fix": {
                    "versions": [],
                    "state": "not-fixed",
                },
            },
            "artifact": {
                "name": "openssl",
                "version": "1.1.1",
            },
        },
    ]
}


@pytest.fixture
async def db_with_containers(tmp_db):
    """Set up a database with pipeline, run, and container records."""
    import aiosqlite

    db = await aiosqlite.connect(tmp_db)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")

    # Insert a pipeline
    await db.execute(
        "INSERT INTO pipelines (id, slug, name, repo_url, platform) VALUES (?, ?, ?, ?, ?)",
        (1, "test-pipeline", "Test Pipeline", "https://github.com/example/test", "github"),
    )

    # Insert a run
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) VALUES (?, ?, ?, ?)",
        (1, 1, "run-1", "success"),
    )

    # Insert containers
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "python:3.11", "sha256:abc123", "linux/amd64", "manifest"),
    )
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, platform, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "redis:7", "sha256:def456", "linux/amd64", "manifest"),
    )

    await db.commit()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Tests for generate_missing_sboms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_finds_images_without_sboms(db_with_containers):
    """generate_missing_sboms should find images in run_containers that lack SBOMs."""
    db = db_with_containers

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.sbom_generator.shutil.which", return_value="/usr/bin/syft"), \
         patch("backend.jobs.sbom_generator.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        from backend.jobs.sbom_generator import generate_missing_sboms

        count = await generate_missing_sboms(db)

    assert count == 2
    # Verify syft was called for both images
    assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_generate_parses_and_stores_sbom(db_with_containers):
    """SBOM output should be parsed and stored in container_sboms."""
    db = db_with_containers

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.sbom_generator.shutil.which", return_value="/usr/bin/syft"), \
         patch("backend.jobs.sbom_generator.asyncio.create_subprocess_exec", return_value=mock_process):
        from backend.jobs.sbom_generator import generate_missing_sboms

        await generate_missing_sboms(db)

    cursor = await db.execute("SELECT * FROM container_sboms")
    rows = await cursor.fetchall()
    assert len(rows) == 2

    # Verify stored SBOM content is valid JSON
    for row in rows:
        sbom_data = json.loads(row[4])  # sbom column
        assert sbom_data["spdxVersion"] == "SPDX-2.3"
        assert row[3] == "spdx-json"  # format column
        assert row[5] == "syft"  # generator column


@pytest.mark.asyncio
async def test_generate_skips_existing_sboms(db_with_containers):
    """Images that already have SBOMs should not be re-generated."""
    db = db_with_containers

    # Pre-insert an SBOM for one image
    await db.execute(
        "INSERT INTO container_sboms (image_digest, image_ref, format, sbom, generator) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sha256:abc123", "python:3.11", "spdx-json", json.dumps(SAMPLE_SPDX_SBOM), "syft"),
    )
    await db.commit()

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.sbom_generator.shutil.which", return_value="/usr/bin/syft"), \
         patch("backend.jobs.sbom_generator.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        from backend.jobs.sbom_generator import generate_missing_sboms

        count = await generate_missing_sboms(db)

    assert count == 1
    assert mock_exec.call_count == 1  # Only called for redis, not python


@pytest.mark.asyncio
async def test_generate_missing_syft_command(db_with_containers):
    """When syft is not installed, the function should log a warning and return 0."""
    db = db_with_containers

    with patch("backend.jobs.sbom_generator.shutil.which", return_value=None):
        from backend.jobs.sbom_generator import generate_missing_sboms

        count = await generate_missing_sboms(db)

    assert count == 0

    # No SBOMs should have been created
    cursor = await db.execute("SELECT COUNT(*) FROM container_sboms")
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_generate_handles_syft_failure_per_image(db_with_containers):
    """If syft fails for one image, it should continue processing others."""
    db = db_with_containers

    call_count = 0

    async def mock_communicate():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (b"", b"error: image not found")
        return (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")

    mock_process = AsyncMock()
    mock_process.communicate = mock_communicate

    # First call fails, second succeeds
    return_codes = iter([1, 0])

    @property
    def mock_returncode(self):
        return next(return_codes)

    # Use side_effect to return different processes
    fail_process = AsyncMock()
    fail_process.communicate.return_value = (b"", b"error: image not found")
    fail_process.returncode = 1

    success_process = AsyncMock()
    success_process.communicate.return_value = (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")
    success_process.returncode = 0

    with patch("backend.jobs.sbom_generator.shutil.which", return_value="/usr/bin/syft"), \
         patch("backend.jobs.sbom_generator.asyncio.create_subprocess_exec", side_effect=[fail_process, success_process]):
        from backend.jobs.sbom_generator import generate_missing_sboms

        count = await generate_missing_sboms(db)

    # One failed, one succeeded
    assert count == 1

    cursor = await db.execute("SELECT COUNT(*) FROM container_sboms")
    row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_generate_skips_null_digests(db_with_containers):
    """Images with NULL or empty digests should be skipped."""
    db = db_with_containers

    # Add a container with no digest
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, source) "
        "VALUES (?, ?, ?, ?)",
        (1, "busybox:latest", None, "manifest"),
    )
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, image_digest, source) "
        "VALUES (?, ?, ?, ?)",
        (1, "alpine:latest", "", "manifest"),
    )
    await db.commit()

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_SPDX_SBOM).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.sbom_generator.shutil.which", return_value="/usr/bin/syft"), \
         patch("backend.jobs.sbom_generator.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        from backend.jobs.sbom_generator import generate_missing_sboms

        count = await generate_missing_sboms(db)

    # Only the 2 original images with valid digests should be processed
    assert count == 2
    assert mock_exec.call_count == 2


# ---------------------------------------------------------------------------
# Tests for scan_sboms_for_vulnerabilities
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_with_sboms(db_with_containers):
    """Extend db_with_containers with stored SBOMs."""
    db = db_with_containers

    await db.execute(
        "INSERT INTO container_sboms (id, image_digest, image_ref, format, sbom, generator) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, "sha256:abc123", "python:3.11", "spdx-json", json.dumps(SAMPLE_SPDX_SBOM), "syft"),
    )
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_scan_parses_grype_output(db_with_sboms):
    """Grype output should be parsed and vulnerabilities stored."""
    db = db_with_sboms

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_GRYPE_OUTPUT).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"), \
         patch("backend.jobs.vulnerability_scanner.asyncio.create_subprocess_exec", return_value=mock_process):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count = await scan_sboms_for_vulnerabilities(db)

    assert count == 2

    cursor = await db.execute(
        "SELECT * FROM sbom_vulnerabilities WHERE sbom_id = 1 ORDER BY vuln_id"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 2

    # Check CVE-2024-1234
    cve1 = rows[0]
    assert cve1[2] == "CVE-2024-1234"  # vuln_id
    assert cve1[3] == "requests"  # package_name
    assert cve1[4] == "2.31.0"  # installed_version
    assert cve1[5] == "2.32.0"  # fixed_version
    assert cve1[6] == "High"  # severity

    # Check CVE-2024-5678 (no fix)
    cve2 = rows[1]
    assert cve2[2] == "CVE-2024-5678"
    assert cve2[3] == "openssl"
    assert cve2[5] is None  # no fixed version
    assert cve2[6] == "Medium"


@pytest.mark.asyncio
async def test_scan_missing_grype_command(db_with_sboms):
    """When grype is not installed, the function should return 0."""
    db = db_with_sboms

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value=None):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count = await scan_sboms_for_vulnerabilities(db)

    assert count == 0

    cursor = await db.execute("SELECT COUNT(*) FROM sbom_vulnerabilities")
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_rescan_replaces_old_vulnerabilities(db_with_sboms):
    """Re-scanning should delete old vulnerabilities and replace with new ones."""
    db = db_with_sboms

    # First scan
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(SAMPLE_GRYPE_OUTPUT).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"), \
         patch("backend.jobs.vulnerability_scanner.asyncio.create_subprocess_exec", return_value=mock_process):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count1 = await scan_sboms_for_vulnerabilities(db)

    assert count1 == 2

    # Second scan with different results (only 1 vulnerability now)
    new_grype_output = {
        "matches": [
            {
                "vulnerability": {
                    "id": "CVE-2024-9999",
                    "severity": "Critical",
                    "fix": {"versions": ["3.0.0"], "state": "fixed"},
                },
                "artifact": {
                    "name": "urllib3",
                    "version": "1.26.0",
                },
            }
        ]
    }

    mock_process2 = AsyncMock()
    mock_process2.communicate.return_value = (json.dumps(new_grype_output).encode(), b"")
    mock_process2.returncode = 0

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"), \
         patch("backend.jobs.vulnerability_scanner.asyncio.create_subprocess_exec", return_value=mock_process2):
        count2 = await scan_sboms_for_vulnerabilities(db)

    assert count2 == 1

    # Only the new vulnerability should exist
    cursor = await db.execute(
        "SELECT * FROM sbom_vulnerabilities WHERE sbom_id = 1"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "CVE-2024-9999"
    assert rows[0][6] == "Critical"


@pytest.mark.asyncio
async def test_scan_handles_grype_failure(db_with_sboms):
    """If grype fails for an SBOM, it should continue (and not crash)."""
    db = db_with_sboms

    # Add a second SBOM
    await db.execute(
        "INSERT INTO container_sboms (id, image_digest, image_ref, format, sbom, generator) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, "sha256:def456", "redis:7", "spdx-json", json.dumps(SAMPLE_SPDX_SBOM), "syft"),
    )
    await db.commit()

    fail_process = AsyncMock()
    fail_process.communicate.return_value = (b"", b"grype error")
    fail_process.returncode = 1

    success_process = AsyncMock()
    success_process.communicate.return_value = (json.dumps(SAMPLE_GRYPE_OUTPUT).encode(), b"")
    success_process.returncode = 0

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"), \
         patch("backend.jobs.vulnerability_scanner.asyncio.create_subprocess_exec", side_effect=[fail_process, success_process]):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count = await scan_sboms_for_vulnerabilities(db)

    # Only vulnerabilities from the successful scan
    assert count == 2


@pytest.mark.asyncio
async def test_scan_no_sboms(db_with_containers):
    """When there are no SBOMs, the scanner should return 0."""
    db = db_with_containers

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count = await scan_sboms_for_vulnerabilities(db)

    assert count == 0


@pytest.mark.asyncio
async def test_scan_empty_matches(db_with_sboms):
    """When grype finds no vulnerabilities, count should be 0."""
    db = db_with_sboms

    empty_output = {"matches": []}

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(empty_output).encode(), b"")
    mock_process.returncode = 0

    with patch("backend.jobs.vulnerability_scanner.shutil.which", return_value="/usr/bin/grype"), \
         patch("backend.jobs.vulnerability_scanner.asyncio.create_subprocess_exec", return_value=mock_process):
        from backend.jobs.vulnerability_scanner import scan_sboms_for_vulnerabilities

        count = await scan_sboms_for_vulnerabilities(db)

    assert count == 0
