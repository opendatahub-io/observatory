import copy

import pytest


@pytest.fixture
def extraction_payload():
    return {
        "run_key": "extract:RFE-42:sha256:abc",
        "source_file": "artifacts/RFE-42/strategy.md",
        "pipeline_slug": "end-to-end",
        "artifact_type": "strategy",
        "artifact_digest": "abc",
        "extractor_revision": "extract-claims@v2",
        "repository_revision": "commit-extract",
        "model": "test-model",
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
                "evaluator_revision": "selector@v1",
            },
            "ambiguity": {"status": "none", "evaluator_revision": "ambiguity@v1"},
            "claims": [{
                "claim_text": "The service must retain immutable histories.",
                "claim_type": "architectural",
                "modality": "must",
                "jira_keys": ["RFE-42"],
                "evaluation": {
                    "evaluator_revision": "extraction-eval@v1",
                    "entailed": True,
                    "coverage_result": "complete",
                    "decontextualization_result": "self_contained",
                    "maximally_contextualized_claim": "Within Observatory, the service must retain immutable histories.",
                    "extracted_retrieval_digest": "sha256:short",
                    "comparison_retrieval_digest": "sha256:maximal",
                    "coverage_elements": [
                        {
                            "element_text": "retain immutable histories",
                            "element_kind": "verifiable",
                            "coverage": "explicit",
                        },
                        {
                            "element_text": "This design is elegant",
                            "element_kind": "unverifiable",
                            "coverage": "omitted",
                        },
                    ],
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


async def test_ingest_extraction_run_is_idempotent(client, extraction_payload):
    extraction_payload["units"][0]["claims"][0]["jira_keys"] = []
    response = await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    assert response.status_code == 201
    result = response.json()
    assert result["created"] is True
    assert len(result["occurrence_ids"]) == 1

    duplicate = await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    assert duplicate.status_code == 201
    assert duplicate.json() == {"id": result["id"], "created": False}

    conflicting = {**extraction_payload, "artifact_digest": "different"}
    conflict = await client.post("/api/v2/claims/extraction-runs", json=conflicting)
    assert conflict.status_code == 409

    runs = await client.get("/api/v2/claims/extraction-runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["occurrence_count"] == 1
    detail = await client.get(f"/api/v2/claims/extraction-runs/{result['id']}")
    assert detail.status_code == 200
    assert detail.json()["source_units"][0]["occurrences"][0]["entailed"] == 1
    assert (
        detail.json()["source_units"][0]["occurrences"][0]["coverage_elements"][0]["coverage"]
        == "explicit"
    )
    assert (
        detail.json()["source_units"][0]["occurrences"][0]["extraction_evidence"][0]["relationship"]
        == "entails"
    )
    summary = await client.get("/api/v2/claims/summary")
    assert summary.status_code == 200
    assert summary.json()["source_entailment_rate"] == 1.0
    assert summary.json()["coverage"]["verifiable_element_f1"] == 1.0
    assert summary.json()["coverage"]["unverifiable_element_f1"] == 1.0
    assert summary.json()["coverage"]["element_macro_f1"] == 1.0
    extraction_breakdown = summary.json()["breakdowns"]["extraction"][0]
    assert extraction_breakdown["artifact_type"] == "strategy"
    assert extraction_breakdown["extractor_revision"] == "extract-claims@v2"
    assert extraction_breakdown["model"] == "test-model"
    assert extraction_breakdown["configuration_digest"] == "sha256:extract-config"
    assert extraction_breakdown["coverage"]["element_macro_f1"] == 1.0
    candidates = await client.get("/api/v2/claims/occurrences?jira_key=RFE-42")
    assert candidates.status_code == 200
    assert candidates.json()["occurrences"][0]["extraction_entailed"] == 1
    receipt = await client.post("/api/v2/claims/stage-receipts", json={
        "stage": "extract-claims", "scope_key": "RFE-42",
        "input_digest": "sha256:abc", "skill_fqn": "repo:extract-claims",
        "skill_revision": "deadbeef", "status": "hit", "agent_job_avoided": True,
    })
    assert receipt.status_code == 201
    summary = await client.get("/api/v2/claims/summary")
    assert summary.json()["receipts"]["agent_jobs_avoided"] == 1


async def test_identical_text_keeps_distinct_source_occurrences(client, extraction_payload):
    first = (
        await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    ).json()
    second_payload = {**extraction_payload, "run_key": "extract:RFE-43:sha256:def"}
    second_payload["source_file"] = "artifacts/RFE-43/security-review.md"
    second_payload["units"] = [
        {**extraction_payload["units"][0], "source_unit": {
            **extraction_payload["units"][0]["source_unit"],
            "unit_key": "unit-2", "source_locator": "security-review.md:9",
        }, "claims": [{
            **extraction_payload["units"][0]["claims"][0], "jira_keys": [],
        }]}
    ]
    second = (
        await client.post("/api/v2/claims/extraction-runs", json=second_payload)
    ).json()
    first_history = (
        await client.get(
            f"/api/v2/claims/occurrences/{first['occurrence_ids'][0]}/history"
        )
    ).json()
    second_history = (
        await client.get(
            f"/api/v2/claims/occurrences/{second['occurrence_ids'][0]}/history"
        )
    ).json()
    assert first["occurrence_ids"][0] != second["occurrence_ids"][0]
    assert (
        first_history["occurrence"]["normalized_claim_id"]
        == second_history["occurrence"]["normalized_claim_id"]
    )
    first_issue = await client.get(
        "/api/v2/claims/occurrences?jira_key=RFE-42&pending_only=false"
    )
    second_issue = await client.get(
        "/api/v2/claims/occurrences?jira_key=RFE-43&pending_only=false"
    )
    assert [item["id"] for item in first_issue.json()["occurrences"]] == [
        first["occurrence_ids"][0]
    ]
    assert [item["id"] for item in second_issue.json()["occurrences"]] == [
        second["occurrence_ids"][0]
    ]


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (
            lambda payload: payload["units"][0]["claims"][0]["evaluation"].update(
                coverage_elements=[]
            ),
            "coverage_elements",
        ),
        (
            lambda payload: payload["units"][0]["claims"][0].update(
                claim_type="requirement"
            ),
            "claim_type",
        ),
        (
            lambda payload: payload["units"][0]["selection"].update(
                classification="mixed", selected_text=None
            ),
            "selected_text",
        ),
        (
            lambda payload: payload["units"][0]["ambiguity"].update(
                status="resolved", clarified_text=None
            ),
            "clarified_text",
        ),
    ],
)
async def test_rejects_unmeasurable_staged_extraction(
    client, extraction_payload, mutate, detail
):
    mutate(extraction_payload)
    response = await client.post(
        "/api/v2/claims/extraction-runs", json=extraction_payload
    )
    assert response.status_code == 422
    assert detail in response.text


async def test_rejects_incomplete_full_decontextualization_comparison(
    client, extraction_payload
):
    evaluation = extraction_payload["units"][0]["claims"][0]["evaluation"]
    evaluation["decontextualization_result"] = "desirable"
    response = await client.post(
        "/api/v2/claims/extraction-runs", json=extraction_payload
    )
    assert response.status_code == 422
    assert "evidence_context_digest" in response.text


async def test_occurrence_keeps_verification_and_explanation_history(
    client, extraction_payload
):
    extraction = (
        await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    ).json()
    occurrence_id = extraction["occurrence_ids"][0]
    verification = await client.post("/api/v2/claims/verification-runs", json={
        "claim_occurrence_id": occurrence_id,
        "verifier_revision": "verify-claims@v2",
        "repository_revision": "commit-verify",
        "model": "verify-model",
        "harness": "agent-eval-harness",
        "configuration_digest": "sha256:verify-config",
        "evidence_context_digest": "sha256:evidence-a",
        "verdict": "supported",
        "confidence": 92,
        "evidence_summary": "The implementation and test agree.",
        "evidence": [{
            "evidence_type": "repository_file",
            "uri": "repo://service/store.py",
            "repository_revision": "deadbeef",
            "source_locator": "store.py:20",
            "relationship": "supports",
            "authority": "implementation",
        }],
    })
    assert verification.status_code == 201
    verification_id = verification.json()["id"]

    second_verification = await client.post("/api/v2/claims/verification-runs", json={
        "claim_occurrence_id": occurrence_id,
        "verifier_revision": "verify-claims@v3",
        "evidence_context_digest": "sha256:evidence-b",
        "verdict": "contradicted",
        "confidence": 81,
        "evidence": [{
            "evidence_type": "repository_file",
            "uri": "repo://service/store.py",
            "relationship": "contradicts",
        }],
    })
    assert second_verification.status_code == 201

    explanation = await client.post("/api/v2/claims/explanation-runs", json={
        "verification_run_id": verification_id,
        "explainer_revision": "explain-claims@v2",
        "repository_revision": "commit-explain",
        "model": "explain-model",
        "harness": "agent-eval-harness",
        "configuration_digest": "sha256:explain-config",
        "category": "context_gap",
        "improvement_target": "retrieval context",
        "explanation": "The initial context omitted the persistence implementation.",
        "contributing_factors": ["implementation source was not retrieved"],
        "remediation": "Add the persistence source to retrieval context.",
        "regression_test": "Include store.py and expect supported.",
        "evidence": [{
            "evidence_type": "verification_log",
            "uri": f"observatory://verification-runs/{verification_id}",
            "relationship": "supports",
        }],
    })
    assert explanation.status_code == 201
    explanation_id = explanation.json()["id"]

    missing_run_override = await client.post("/api/v2/claims/human-overrides", json={
        "claim_occurrence_id": occurrence_id,
        "actor": "reviewer@example.test",
        "decision": "allow_with_followup",
        "rationale": "An immutable verification target is required.",
    })
    assert missing_run_override.status_code == 422

    wrong_run_override = await client.post("/api/v2/claims/human-overrides", json={
        "claim_occurrence_id": occurrence_id,
        "verification_run_id": 999999,
        "actor": "reviewer@example.test",
        "decision": "allow_with_followup",
        "rationale": "A different or missing verification run must be rejected.",
    })
    assert wrong_run_override.status_code == 409

    override = await client.post("/api/v2/claims/human-overrides", json={
        "claim_occurrence_id": occurrence_id,
        "verification_run_id": verification_id,
        "actor": "reviewer@example.test",
        "decision": "allow_with_followup",
        "rationale": "The discrepancy is non-blocking for this demonstration.",
    })
    assert override.status_code == 201

    regression = await client.post("/api/v2/claims/regression-runs", json={
        "explanation_run_id": explanation_id,
        "dataset_fqn": "github.local/opendatahub-io/eval-datasets@main:claim-assurance",
        "implementation_revision": "extract-claims@fixed",
        "status": "passed",
        "metrics": {"source_entailment_rate": 1.0},
    })
    assert regression.status_code == 201

    history = await client.get(f"/api/v2/claims/occurrences/{occurrence_id}/history")
    assert history.status_code == 200
    result = history.json()
    assert result["occurrence"]["modality"] == "must"
    assert len(result["verification_runs"]) == 2
    assert result["verification_runs"][0]["model"] == "verify-model"
    assert result["verification_runs"][0]["repository_revision"] == "commit-verify"
    assert result["verification_runs"][0]["explanation_runs"][0]["category"] == "context_gap"
    assert result["verification_runs"][0]["explanation_runs"][0]["model"] == "explain-model"
    assert (
        result["verification_runs"][0]["explanation_runs"][0]["repository_revision"]
        == "commit-explain"
    )

    summary = (await client.get("/api/v2/claims/summary")).json()
    verification_breakdown = next(
        item for item in summary["breakdowns"]["verification"]
        if item["model"] == "verify-model"
    )
    assert verification_breakdown["configuration_digest"] == "sha256:verify-config"
    explanation_breakdown = next(
        item for item in summary["breakdowns"]["explanation"]
        if item["model"] == "explain-model"
    )
    assert explanation_breakdown["recurrence_rate"] == 1.0

    effective = await client.get(
        f"/api/v2/claims/occurrences/{occurrence_id}/effective-verdict"
    )
    assert effective.status_code == 200
    assert effective.json()["verdict"] == "contradicted"


async def test_legacy_claim_rows_are_backfilled_once(tmp_db):
    from backend.database import get_db, init_schema

    db = await get_db()
    await db.execute(
        "INSERT INTO claims (claim_text, claim_hash) VALUES ('Legacy claim', 'legacy-hash')"
    )
    claim_id = (await (await db.execute("SELECT last_insert_rowid() AS id")).fetchone())["id"]
    await db.execute(
        """INSERT INTO claim_sources (claim_id, source_file, pipeline_slug, original_text)
           VALUES (?, 'legacy.md', 'legacy', 'Legacy claim')""",
        (claim_id,),
    )
    await db.execute(
        """INSERT INTO claim_verdicts (claim_id, verdict, confidence)
           VALUES (?, 'supported', 70)""",
        (claim_id,),
    )
    await db.commit()

    await init_schema(db)
    await init_schema(db)
    occurrence_count = await db.execute(
        "SELECT COUNT(*) AS count FROM claim_occurrences WHERE normalized_claim_id = ?",
        (claim_id,),
    )
    assert (await occurrence_count.fetchone())["count"] == 1
    verification_count = await db.execute(
        """SELECT COUNT(*) AS count FROM claim_verification_runs cvr
           JOIN claim_occurrences co ON co.id = cvr.claim_occurrence_id
           WHERE co.normalized_claim_id = ?""",
        (claim_id,),
    )
    assert (await verification_count.fetchone())["count"] == 1


async def test_v2_triage_uses_effective_occurrence_state_and_preserves_duplicates(
    client, extraction_payload, tmp_db
):
    first = (
        await client.post("/api/v2/claims/extraction-runs", json=extraction_payload)
    ).json()
    second_payload = copy.deepcopy(extraction_payload)
    second_payload["run_key"] = "extract:RFE-43:sha256:duplicate"
    second_payload["source_file"] = "artifacts/RFE-43/strategy.md"
    second_payload["units"][0]["source_unit"]["unit_key"] = "unit-duplicate"
    second_payload["units"][0]["source_unit"]["source_locator"] = "strategy.md:12"
    second_payload["units"][0]["claims"][0]["jira_keys"] = ["RFE-43"]
    second = (
        await client.post("/api/v2/claims/extraction-runs", json=second_payload)
    ).json()
    occurrence_id = first["occurrence_ids"][0]

    old_verification = await client.post("/api/v2/claims/verification-runs", json={
        "claim_occurrence_id": occurrence_id,
        "verifier_revision": "verify@old",
        "evidence_context_digest": "sha256:old",
        "verdict": "supported",
        "severity": "info",
        "confidence": 70,
        "evidence": [{
            "evidence_type": "repository_file", "uri": "repo://old",
            "relationship": "supports",
        }],
    })
    assert old_verification.status_code == 201
    effective_verification = await client.post(
        "/api/v2/claims/verification-runs", json={
            "claim_occurrence_id": occurrence_id,
            "verifier_revision": "verify@new",
            "evidence_context_digest": "sha256:new",
            "verdict": "contradicted",
            "severity": "high",
            "confidence": 96,
            "evidence_summary": "Versioned evidence contradicts the occurrence.",
            "evidence": [{
                "evidence_type": "repository_file", "uri": "repo://new",
                "relationship": "contradicts",
            }],
        },
    )
    verification_id = effective_verification.json()["id"]
    explanation = await client.post("/api/v2/claims/explanation-runs", json={
        "verification_run_id": verification_id,
        "explainer_revision": "explain@new",
        "category": "context_gap",
        "improvement_target": "architecture context",
        "explanation": "The versioned source was absent from generation context.",
        "alternative_explanations": ["Retrieval may have omitted an available source."],
        "remediation": "Add the source to versioned context.",
        "regression_test": "Replay with the source and expect support.",
        "human_review_required": True,
        "evidence": [{
            "evidence_type": "verification_log", "uri": "observatory://verification",
            "relationship": "supports",
        }],
    })
    explanation_id = explanation.json()["id"]
    await client.post("/api/v2/claims/regression-runs", json={
        "explanation_run_id": explanation_id,
        "dataset_fqn": "local:test", "implementation_revision": "fixed",
        "status": "passed", "metrics": {"accuracy": 1.0},
    })

    summary = (await client.get("/api/v2/claims/triage/summary")).json()
    assert summary == {
        "total_occurrences": 2,
        "verified": 1,
        "pending": 1,
        "supported": 0,
        "contradicted": 1,
        "insufficient_evidence": 0,
        "not_applicable": 0,
        "explained": 1,
        "human_review_required": 1,
        "jira_keys_referenced": 2,
    }

    rows = (await client.get(
        "/api/v2/claims/triage/occurrences?sort=claim&sort_dir=asc"
    )).json()
    assert rows["total"] == 2
    assert {row["id"] for row in rows["occurrences"]} == {
        occurrence_id, second["occurrence_ids"][0],
    }
    assert len({row["normalized_claim_id"] for row in rows["occurrences"]}) == 1
    effective = next(row for row in rows["occurrences"] if row["id"] == occurrence_id)
    assert effective["verdict"] == "contradicted"
    assert effective["confidence"] == 96
    assert effective["severity"] == "high"
    assert effective["explanation_category"] == "context_gap"
    assert effective["improvement_target"] == "architecture context"
    assert effective["processing_state"] == "explanation_requires_human_review"
    pending = next(
        row for row in rows["occurrences"] if row["id"] == second["occurrence_ids"][0]
    )
    assert pending["processing_state"] == "not_verified"

    filtered = (await client.get(
        "/api/v2/claims/triage/occurrences"
        "?verdict=contradicted&jira_key=RFE-42"
    )).json()
    assert [row["id"] for row in filtered["occurrences"]] == [occurrence_id]
    assert (
        await client.get("/api/v2/claims/triage/occurrences?verdict=supported")
    ).json()["total"] == 0

    issues = (await client.get("/api/v2/claims/triage/issues")).json()
    by_issue = {row["jira_key"]: row for row in issues["issues"]}
    assert by_issue["RFE-42"]["contradicted"] == 1
    assert by_issue["RFE-43"]["pending"] == 1

    explanations = (await client.get(
        "/api/v2/claims/triage/explanations"
        "?category=context_gap&improvement_target=architecture%20context"
        "&jira_key=RFE-42&human_review_required=true"
    )).json()
    assert explanations["total"] == 1
    assert explanations["explanations"][0]["claim_occurrence_id"] == occurrence_id
    assert explanations["explanations"][0]["alternative_explanations"] == [
        "Retrieval may have omitted an available source."
    ]
    facets = (await client.get(
        "/api/v2/claims/triage/explanation-facets"
    )).json()
    assert facets["categories"] == [{"value": "context_gap", "count": 1}]

    history = (await client.get(
        f"/api/v2/claims/occurrences/{occurrence_id}/history"
    )).json()
    assert history["effective_verification_run_id"] == verification_id
    assert history["effective_explanation_run_id"] == explanation_id
    assert history["processing_state"] == "explanation_requires_human_review"
    assert history["jira_keys"] == ["RFE-42"]
    assert history["verification_runs"][-1]["explanation_runs"][0][
        "regression_runs"
    ][0]["metrics"] == {"accuracy": 1.0}

    from backend.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO claims (claim_text, claim_hash) VALUES ('Legacy only', 'legacy-only')"
    )
    legacy_id = (await (await db.execute(
        "SELECT last_insert_rowid() AS id"
    )).fetchone())["id"]
    await db.execute(
        "INSERT INTO claim_verdicts (claim_id, verdict, confidence) VALUES (?, 'supported', 99)",
        (legacy_id,),
    )
    await db.commit()
    assert (await client.get("/api/v2/claims/triage/summary")).json()[
        "total_occurrences"
    ] == 2
