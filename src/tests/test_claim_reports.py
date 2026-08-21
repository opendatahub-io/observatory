import copy
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def extraction_payload():
    return {
        "run_key": "extract:RFE-42:sha256:report",
        "source_file": "artifacts/RFE-42/strategy.md",
        "pipeline_slug": "end-to-end",
        "artifact_type": "strategy",
        "artifact_digest": "abc",
        "extractor_revision": "extract-claims@report",
        "repository_revision": "commit-extract",
        "model": "extract-model",
        "harness": "agent-eval-harness",
        "configuration_digest": "sha256:extract-config",
        "configuration": {"temperature": 0},
        "units": [{
            "source_unit": {
                "unit_key": "unit-1",
                "unit_kind": "sentence",
                "source_locator": "strategy.md:4",
                "original_text": "The service must retain immutable histories.",
                "heading_path": ["Persistence"],
            },
            "selection": {
                "classification": "verifiable",
                "selected_text": "The service must retain immutable histories.",
                "evaluator_revision": "selector@report",
            },
            "ambiguity": {"status": "none", "evaluator_revision": "ambiguity@report"},
            "claims": [{
                "claim_text": "The service must retain immutable histories.",
                "claim_type": "architectural",
                "modality": "must",
                "jira_keys": ["RFE-42"],
                "evaluation": {
                    "evaluator_revision": "extraction-eval@report",
                    "entailed": True,
                    "coverage_result": "complete",
                    "decontextualization_result": "self_contained",
                    "coverage_elements": [{
                        "element_text": "retain immutable histories",
                        "element_kind": "verifiable",
                        "coverage": "explicit",
                    }],
                    "evidence": [{
                        "evidence_type": "source_unit",
                        "uri": "artifact://strategy.md",
                        "source_locator": "strategy.md:4",
                        "relationship": "entails",
                    }],
                },
            }],
        }],
    }


async def _seed_report_fixture(client, extraction_payload):
    extraction = (
        await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    ).json()
    occurrence_id = extraction["occurrence_ids"][0]
    verification = await client.post("/api/v2/claims/verification-runs", json={
        "claim_occurrence_id": occurrence_id,
        "verifier_revision": "verify-claims@report",
        "repository_revision": "commit-verify",
        "model": "verify-model",
        "harness": "agent-eval-harness",
        "configuration_digest": "sha256:verify-config",
        "evidence_context_digest": "sha256:evidence-report",
        "verdict": "contradicted",
        "severity": "high",
        "confidence": 95,
        "evidence_summary": "The source implementation contradicts the claim.",
        "evidence": [{
            "evidence_type": "repository_file",
            "uri": "repo://service/store.py",
            "repository_revision": "deadbeef",
            "source_locator": "store.py:20",
            "relationship": "contradicts",
            "authority": "implementation",
        }],
    })
    verification_id = verification.json()["id"]
    explanation = await client.post("/api/v2/claims/explanation-runs", json={
        "verification_run_id": verification_id,
        "explainer_revision": "explain-claims@report",
        "repository_revision": "commit-explain",
        "model": "explain-model",
        "harness": "agent-eval-harness",
        "configuration_digest": "sha256:explain-config",
        "category": "context_gap",
        "improvement_target": "architecture context",
        "explanation": "The generator did not receive the versioned persistence source.",
        "contributing_factors": ["store.py was missing"],
        "alternative_explanations": ["retrieval may have failed"],
        "remediation": "Add store.py to the evidence package.",
        "regression_test": "Replay with store.py and expect support.",
        "human_review_required": True,
        "evidence": [{
            "evidence_type": "verification_log",
            "uri": f"observatory://verification-runs/{verification_id}",
            "relationship": "supports",
        }],
    })
    explanation_id = explanation.json()["id"]
    await client.post("/api/v2/claims/regression-runs", json={
        "explanation_run_id": explanation_id,
        "dataset_fqn": "local:claim-report",
        "implementation_revision": "fixed",
        "status": "passed",
        "metrics": {"accuracy": 1.0},
    })
    await client.post("/api/v2/claims/human-overrides", json={
        "claim_occurrence_id": occurrence_id,
        "verification_run_id": verification_id,
        "actor": "reviewer@example.test",
        "decision": "needs_followup",
        "rationale": "Route to the owning project asynchronously.",
    })
    history = (await client.get(
        f"/api/v2/claims/occurrences/{occurrence_id}/history"
    )).json()
    group = await client.post("/api/v2/claim-consolidation/groups", json={
        "canonical_text": "The service retains immutable histories.",
        "normalized_claim_ids": [history["occurrence"]["normalized_claim_id"]],
        "subject_key": "service-history",
        "qualifier_summary": {"scope": "test"},
        "policy_revision": "human-review@report",
        "actor": "reviewer@example.test",
    })
    assert group.status_code == 201
    return occurrence_id, verification_id, explanation_id, history["occurrence"]["normalized_claim_id"]


async def test_claim_assurance_json_export_is_self_contained(
    client, extraction_payload
):
    occurrence_id, verification_id, explanation_id, normalized_claim_id = await _seed_report_fixture(
        client, extraction_payload
    )

    response = await client.get(
        "/api/v2/claims/reports/export.json"
        "?jira_key=RFE-42&observatory_url=http://observatory.local"
    )

    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == "claim-assurance-report.v1"
    assert report["observatory_url"] == "http://observatory.local"
    assert report["filters"] == {"jira_key": "RFE-42"}
    assert report["summary"]["exported_occurrences"] == 1
    assert report["summary"]["contradicted"] == 1
    assert report["summary"]["human_review_required"] == 1
    occurrence = report["occurrences"][0]
    assert occurrence["id"] == occurrence_id
    assert occurrence["source"]["file"] == "artifacts/RFE-42/strategy.md"
    assert occurrence["extraction_evaluation"]["coverage_elements"][0]["coverage"] == "explicit"
    assert occurrence["canonical_group"]["canonical_text"] == "The service retains immutable histories."
    assert occurrence["effective_verification_run_id"] == verification_id
    assert occurrence["effective_explanation_run_id"] == explanation_id
    verification = occurrence["verification_runs"][0]
    assert verification["evidence"][0]["relationship"] == "contradicts"
    explanation = verification["explanation_runs"][0]
    assert explanation["contributing_factors"] == ["store.py was missing"]
    assert explanation["regression_runs"][0]["metrics"] == {"accuracy": 1.0}
    assert occurrence["human_overrides"][0]["decision"] == "needs_followup"
    assert report["canonical_groups"][0]["memberships"][0]["normalized_claim_id"] == normalized_claim_id
    assert report["aggregates"]["by_improvement_target"] == [
        {"value": "architecture context", "count": 1}
    ]


async def test_claim_assurance_export_filters_and_markdown(client, extraction_payload):
    await _seed_report_fixture(client, extraction_payload)
    pending_payload = copy.deepcopy(extraction_payload)
    pending_payload["run_key"] = "extract:RFE-43:sha256:pending-report"
    pending_payload["source_file"] = "artifacts/RFE-43/strategy.md"
    pending_payload["units"][0]["source_unit"]["unit_key"] = "unit-pending"
    pending_payload["units"][0]["claims"][0]["jira_keys"] = ["RFE-43"]
    await client.post("/api/v2/claims/extraction-runs", json=pending_payload)

    filtered = await client.get("/api/v2/claims/reports/export.json?verdict=pending")
    assert filtered.status_code == 200
    assert filtered.json()["summary"]["pending"] == 1
    assert filtered.json()["occurrences"][0]["processing_state"] == "not_verified"

    markdown = await client.get("/api/v2/claims/reports/export.md?verdict=contradicted")
    assert markdown.status_code == 200
    text = markdown.text
    assert "# Claim Assurance Report" in text
    assert "## Hotspots" in text
    assert "Effective verdict: `contradicted`" in text
    assert "Add store.py to the evidence package." in text


async def test_claim_report_jobs_persist_and_download_artifacts(
    client, extraction_payload
):
    await _seed_report_fixture(client, extraction_payload)

    created = await client.post("/api/v2/claims/reports", json={
        "report_format": "both",
        "filters": {"jira_key": "RFE-42"},
        "observatory_url": "http://observatory.local",
        "limit": 1000,
    })

    assert created.status_code == 201
    job = created.json()
    assert job["status"] == "complete"
    assert job["report_format"] == "both"
    assert job["filters"] == {"jira_key": "RFE-42"}
    assert job["summary"]["exported_occurrences"] == 1
    assert job["has_json"] is True
    assert job["has_markdown"] is True

    detail = await client.get(f"/api/v2/claims/reports/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["expires_at"] is not None

    json_download = await client.get(
        f"/api/v2/claims/reports/{job['id']}/download?format=json"
    )
    assert json_download.status_code == 200
    assert json_download.json()["schema_version"] == "claim-assurance-report.v1"

    markdown_download = await client.get(
        f"/api/v2/claims/reports/{job['id']}/download?format=markdown"
    )
    assert markdown_download.status_code == 200
    assert "# Claim Assurance Report" in markdown_download.text


async def test_claim_report_job_download_respects_requested_format(
    client, extraction_payload
):
    await _seed_report_fixture(client, extraction_payload)
    created = await client.post("/api/v2/claims/reports", json={
        "report_format": "json",
        "filters": {"jira_key": "RFE-42"},
    })

    job_id = created.json()["id"]
    assert (await client.get(
        f"/api/v2/claims/reports/{job_id}/download?format=json"
    )).status_code == 200
    assert (await client.get(
        f"/api/v2/claims/reports/{job_id}/download?format=markdown"
    )).status_code == 404


def test_export_claim_assurance_report_cli_writes_requested_formats(
    tmp_path, monkeypatch, capsys
):
    script = Path("scripts/export-claim-assurance-report.py").resolve()
    spec = importlib.util.spec_from_file_location("claim_report_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def fake_fetch(base_url, suffix, params):
        calls.append((base_url, suffix, params))
        if suffix.endswith("json"):
            return json.dumps({"summary": {"exported_occurrences": 1}}).encode()
        return b"# Claim Assurance Report\n"

    monkeypatch.setattr(module, "_fetch", fake_fetch)
    output = tmp_path / "snapshot"
    monkeypatch.setattr(
        "sys.argv",
        [
            "export-claim-assurance-report.py", "--api-base-url", "http://test",
            "--jira-key", "RFE-42", "--format", "both", "--output", str(output),
        ],
    )

    assert module.main() == 0
    assert (tmp_path / "snapshot.json").exists()
    assert (tmp_path / "snapshot.md").read_text() == "# Claim Assurance Report\n"
    assert "exported_occurrences=1" in capsys.readouterr().out
    assert calls[0][2]["jira_key"] == "RFE-42"
    assert calls[0][2]["observatory_url"] == "http://test"


def test_export_claim_assurance_report_cli_prints_counts_for_markdown_only(
    tmp_path, monkeypatch, capsys
):
    script = Path("scripts/export-claim-assurance-report.py").resolve()
    spec = importlib.util.spec_from_file_location("claim_report_cli_md", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fake_fetch(_base_url, suffix, _params):
        if suffix.endswith("json"):
            return json.dumps({
                "summary": {"matching_occurrences": 2, "exported_occurrences": 2}
            }).encode()
        return b"# Claim Assurance Report\n"

    monkeypatch.setattr(module, "_fetch", fake_fetch)
    output = tmp_path / "snapshot.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "export-claim-assurance-report.py", "--api-base-url", "http://test",
            "--jira-key", "RFE-42", "--format", "markdown", "--output", str(output),
        ],
    )

    assert module.main() == 0
    assert output.read_text() == "# Claim Assurance Report\n"
    assert "matching_occurrences=2 exported_occurrences=2" in capsys.readouterr().out


def test_export_claim_assurance_report_cli_requires_scope(monkeypatch, tmp_path):
    script = Path("scripts/export-claim-assurance-report.py").resolve()
    spec = importlib.util.spec_from_file_location("claim_report_cli_scope", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        "sys.argv",
        [
            "export-claim-assurance-report.py", "--api-base-url", "http://test",
            "--output", str(tmp_path / "snapshot"),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "provide at least one scope filter" in str(exc)
    else:
        raise AssertionError("unscoped CLI export should fail without --all")
