import copy

import pytest

from backend.crud.claim_assurance import _digest


@pytest.fixture
def extraction_payload():
    text = "The service must retain immutable histories."
    return {
        "run_key": "template",
        "source_file": "template.md",
        "pipeline_slug": "semantic-test",
        "artifact_type": "strategy",
        "extractor_revision": "extract-claims@v2",
        "units": [{
            "source_unit": {
                "unit_key": "unit-template",
                "unit_kind": "sentence",
                "source_locator": "template.md:1",
                "original_text": text,
            },
            "selection": {
                "classification": "verifiable",
                "selected_text": text,
                "evaluator_revision": "selector@v1",
            },
            "ambiguity": {"status": "none", "evaluator_revision": "ambiguity@v1"},
            "claims": [{
                "claim_text": text,
                "original_text": text,
                "claim_type": "architectural",
                "evaluation": {
                    "evaluator_revision": "extraction-eval@v1",
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
                        "uri": "artifact://template.md",
                        "relationship": "entails",
                    }],
                },
            }],
        }],
    }


async def _ingest_claim(
    client, template: dict, *, run: int, text: str, version: str
) -> tuple[int, int]:
    payload = copy.deepcopy(template)
    payload["run_key"] = f"semantic-run-{run}"
    payload["source_file"] = f"artifacts/RHAI-{run}/inventory.md"
    unit = payload["units"][0]
    unit["source_unit"].update({
        "unit_key": f"unit-{run}",
        "source_locator": f"inventory.md:{run}",
        "original_text": text,
    })
    unit["selection"]["selected_text"] = text
    claim = unit["claims"][0]
    claim.update({
        "claim_text": text,
        "original_text": text,
        "claim_type": "scope",
        "modality": "fact",
        "product_version": version,
    })
    claim["evaluation"].update({
        "maximally_contextualized_claim": text,
        "coverage_elements": [{
            "element_text": "rhai-cli component inventory membership",
            "element_kind": "verifiable",
            "coverage": "explicit",
        }],
    })
    response = await client.post("/api/v2/claims/extraction-runs", json=payload)
    assert response.status_code == 201, response.text
    occurrence_id = response.json()["occurrence_ids"][0]
    history = (
        await client.get(f"/api/v2/claims/occurrences/{occurrence_id}/history")
    ).json()
    return occurrence_id, history["occurrence"]["normalized_claim_id"]


async def test_candidate_generation_is_bounded_revisioned_and_idempotent(
    client, extraction_payload
):
    _, first_claim = await _ingest_claim(
        client, extraction_payload, run=1,
        text="rhai-cli is not part of the shipped RHOAI component inventory.",
        version="3.5-ea.2",
    )
    _, second_claim = await _ingest_claim(
        client, extraction_payload, run=2,
        text="The RHOAI component inventory does not include an rhai-cli component.",
        version="3.5-ea.2",
    )
    await _ingest_claim(
        client, extraction_payload, run=3,
        text="The RHOAI 3.6 component inventory excludes rhai-cli.",
        version="3.6",
    )

    request = {
        "run_key": "semantic-backfill-v1",
        "retrieval_revision": "fts5-v1",
        "batch_size": 10,
        "shortlist_size": 2,
    }
    generated = await client.post(
        "/api/v2/claim-consolidation/candidates/generate", json=request
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["created"] > 0
    assert generated.json()["receipt"]["status"] == "complete"

    replay = await client.post(
        "/api/v2/claim-consolidation/candidates/generate", json=request
    )
    assert replay.json()["replayed"] is True
    assert replay.json()["created"] == 0
    conflict = await client.post(
        "/api/v2/claim-consolidation/candidates/generate",
        json={**request, "retrieval_revision": "fts5-v2"},
    )
    assert conflict.status_code == 409

    candidates = (
        await client.get("/api/v2/claim-consolidation/candidates?limit=20")
    ).json()["candidates"]
    pair = next(
        item for item in candidates
        if {item["left_normalized_claim_id"], item["right_normalized_claim_id"]}
        == {first_claim, second_claim}
    )
    assert pair["retrieval_method"] == "sqlite_fts5_bm25"
    assert pair["retrieval_query"]
    comparison = {
        field: {"left": None, "right": None, "compatible": None}
        for field in (
            "subject", "asserted_relationship", "negation", "product_version",
            "temporal_scope", "modality", "inventory_scope", "clarifications",
        )
    }
    comparison["mutual_entailment"] = "uncertain"
    model_shadow = await client.post(
        "/api/v2/claim-consolidation/decisions/model-shadow",
        json={
            "candidate_id": pair["id"], "decision": "needs_review",
            "rationale": "Inventory scope needs human resolution.",
            "compared_qualifiers": comparison,
            "decider_revision": "semantic-judge@v1", "confidence": 0.4,
        },
    )
    assert model_shadow.status_code == 201, model_shadow.text
    assert model_shadow.json() == {
        "decision_id": model_shadow.json()["decision_id"],
        "shadow": True,
        "grouped": False,
    }


async def test_gate_status_reports_missing_authorization_evidence(client):
    status = await client.get("/api/v2/claim-consolidation/gate-status")

    assert status.status_code == 200
    body = status.json()
    assert body["automatic_assignment"]["authorized"] is False
    assert "missing evaluation_record" in body["automatic_assignment"]["reasons"]
    assert body["verification_reuse"]["authorized"] is False
    assert "no simulated reused verification runs were measured" in body[
        "verification_reuse"
    ]["reasons"]


async def test_review_group_split_preserves_occurrence_verification_history(
    client, extraction_payload
):
    first_occurrence, first_claim = await _ingest_claim(
        client, extraction_payload, run=11,
        text="rhai-cli is not part of the shipped RHOAI component inventory.",
        version="3.5-ea.2",
    )
    second_occurrence, second_claim = await _ingest_claim(
        client, extraction_payload, run=12,
        text="The RHOAI component inventory does not include an rhai-cli component.",
        version="3.5-ea.2",
    )
    for occurrence_id in (first_occurrence, second_occurrence):
        verification = await client.post("/api/v2/claims/verification-runs", json={
            "claim_occurrence_id": occurrence_id,
            "verifier_revision": "verify@v1",
            "evidence_context_digest": "sha256:shared-context",
            "verdict": "supported",
            "confidence": 99,
            "token_count": 100,
            "cost_usd": 0.5,
            "evidence": [{
                "evidence_type": "architecture_inventory",
                "uri": "repo://inventory.yaml",
                "relationship": "supports",
            }],
        })
        assert verification.status_code == 201
    invalidated_verification = await client.post("/api/v2/claims/verification-runs", json={
        "claim_occurrence_id": second_occurrence,
        "verifier_revision": "verify@v2",
        "evidence_context_digest": "sha256:shared-context",
        "verdict": "supported",
        "confidence": 99,
        "evidence": [{
            "evidence_type": "architecture_inventory",
            "uri": "repo://inventory.yaml",
            "relationship": "supports",
        }],
    })
    assert invalidated_verification.status_code == 201

    await client.post("/api/v2/claim-consolidation/candidates/generate", json={
        "run_key": "review-v1", "retrieval_revision": "fts5-v1",
        "batch_size": 10, "shortlist_size": 5,
    })
    candidates = (
        await client.get("/api/v2/claim-consolidation/candidates?limit=20")
    ).json()["candidates"]
    candidate = next(
        item for item in candidates
        if {item["left_normalized_claim_id"], item["right_normalized_claim_id"]}
        == {first_claim, second_claim}
    )
    shadow = await client.post("/api/v2/claim-consolidation/decisions/shadow", json={
        "decision_revision": "qualifier-policy-v1", "limit": 20,
    })
    assert shadow.status_code == 200
    assert shadow.json()["counts"]["needs_review"] >= 1

    reviewed = await client.post(
        f"/api/v2/claim-consolidation/candidates/{candidate['id']}/decisions",
        json={
            "decision": "equivalent",
            "rationale": "Both claims mutually entail inventory exclusion under 3.5-ea.2.",
            "compared_qualifiers": {
                "product_version": "3.5-ea.2", "inventory_scope": "component",
                "negation": "compatible", "modality": "fact",
            },
            "decider_revision": "human-review-v1",
            "confidence": 1,
            "actor": "reviewer@example.test",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    group_id = reviewed.json()["canonical_group_id"]
    group = (
        await client.get(f"/api/v2/claim-consolidation/groups/{group_id}")
    ).json()
    assert {member["normalized_claim_id"] for member in group["members"]} == {
        first_claim, second_claim,
    }
    assert {item["id"] for member in group["members"] for item in member["occurrences"]} == {
        first_occurrence, second_occurrence,
    }
    first_history = (
        await client.get(f"/api/v2/claims/occurrences/{first_occurrence}/history")
    ).json()
    assert first_history["occurrence"]["canonical_group_id"] == group_id
    assert len(first_history["verification_runs"]) == 1

    opportunities = (
        await client.get(
            "/api/v2/claim-consolidation/verification-reuse-opportunities"
        )
    ).json()
    assert opportunities["reuse_enabled"] is False
    assert opportunities["reuse_policy"]["status"] == "simulation_only"
    assert opportunities["opportunities"][0]["agreement"] is True
    assert opportunities["opportunities"][0]["simulated_reuse_count"] == 1
    assert opportunities["opportunities"][0]["estimated_saved_tokens"] == 100
    assert opportunities["simulation"]["simulated_reused_run_count"] == 1
    assert opportunities["simulation"]["simulated_agreeing_reuse_count"] == 1
    assert opportunities["invalidation"]["reason_group_counts"]["verifier_revision"] == 1
    evaluation = await client.post("/api/v2/claim-consolidation/evaluations", json={
        "evaluation_run_id": "gate-eval-v1",
        "labeled_dataset_revision": "representative-v1",
        "retrieval_revision": "fts5-v1",
        "decision_revision": "model-v1",
        "candidate_count": 2,
        "labeled_pair_count": 2,
        "equivalent_prediction_count": 1,
        "true_positive_count": 1,
        "false_positive_count": 0,
        "false_negative_count": 0,
        "precision": 1,
        "recall": 1,
        "false_merge_rate": 0,
    })
    assert evaluation.status_code == 201
    gate_status = (await client.get("/api/v2/claim-consolidation/gate-status")).json()
    assert gate_status["automatic_assignment"]["authorized"] is True
    assert gate_status["verification_reuse"]["authorized"] is True

    split = await client.post(
        f"/api/v2/claim-consolidation/groups/{group_id}/split",
        json={
            "normalized_claim_ids": [second_claim],
            "actor": "reviewer@example.test",
            "policy_revision": "human-review-v2",
        },
    )
    assert split.status_code == 200
    second_history = (
        await client.get(f"/api/v2/claims/occurrences/{second_occurrence}/history")
    ).json()
    assert second_history["occurrence"]["canonical_group_id"] is None
    assert len(second_history["verification_runs"]) == 2


async def test_structured_incompatibility_and_automatic_kill_switch(
    client, extraction_payload
):
    await _ingest_claim(
        client, extraction_payload, run=21,
        text="RHOAI includes rhai-cli in its component inventory.", version="3.5",
    )
    await _ingest_claim(
        client, extraction_payload, run=22,
        text="RHOAI includes an rhai-cli component in its inventory.", version="3.6",
    )
    await client.post("/api/v2/claim-consolidation/candidates/generate", json={
        "run_key": "versions-v1", "retrieval_revision": "fts5-v1",
        "batch_size": 10, "shortlist_size": 5,
    })
    shadow = await client.post("/api/v2/claim-consolidation/decisions/shadow", json={
        "decision_revision": "qualifier-policy-v1", "limit": 20,
    })
    assert shadow.json()["counts"]["distinct"] >= 1

    policy = await client.put("/api/v2/claim-consolidation/policies/safe-v1", json={
        "revision": "safe-v1",
        "automatic_assignment_enabled": False,
        "kill_switch": True,
    })
    assert policy.status_code == 200
    automatic = await client.post("/api/v2/claim-consolidation/automatic/safe-v1")
    assert automatic.status_code == 409


def test_exact_text_identity_normalization_contract_is_stable():
    assert _digest(" Claim Text ") == _digest("claim text")
    assert _digest("claim  text") != _digest("claim text")
    assert _digest("claim text.") != _digest("claim text")
    assert _digest("café") != _digest("cafe\u0301")


async def test_claim_fts_synchronizes_insert_update_and_delete(client):
    from backend.database import get_db

    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO claims (claim_text, claim_type, claim_hash) VALUES (?, ?, ?)",
        ("alpha semantic marker", "factual", "fts-sync-alpha"),
    )
    claim_id = cursor.lastrowid
    await db.commit()
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claims_fts WHERE claims_fts MATCH 'alpha'"
    )).fetchone())["n"] == 1

    await db.execute(
        "UPDATE claims SET claim_text = 'beta semantic marker' WHERE id = ?", (claim_id,)
    )
    await db.commit()
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claims_fts WHERE claims_fts MATCH 'alpha'"
    )).fetchone())["n"] == 0
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claims_fts WHERE claims_fts MATCH 'beta'"
    )).fetchone())["n"] == 1

    await db.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
    await db.commit()
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claims_fts WHERE claims_fts MATCH 'beta'"
    )).fetchone())["n"] == 0


async def test_reviewed_equivalence_merges_existing_groups_append_only(client):
    from backend.database import get_db

    db = await get_db()
    claim_ids = []
    for index in range(4):
        cursor = await db.execute(
            "INSERT INTO claims (claim_text, claim_type, claim_hash) VALUES (?, ?, ?)",
            (f"merge claim {index}", "factual", f"merge-hash-{index}"),
        )
        claim_ids.append(cursor.lastrowid)
    await db.commit()
    first_group = await client.post("/api/v2/claim-consolidation/groups", json={
        "canonical_text": "First reviewed group",
        "normalized_claim_ids": claim_ids[:2],
        "policy_revision": "human-v1", "actor": "reviewer@example.test",
    })
    second_group = await client.post("/api/v2/claim-consolidation/groups", json={
        "canonical_text": "Second reviewed group",
        "normalized_claim_ids": claim_ids[2:],
        "policy_revision": "human-v1", "actor": "reviewer@example.test",
    })
    assert first_group.status_code == second_group.status_code == 201
    cursor = await db.execute(
        """INSERT INTO claim_similarity_candidates
           (left_normalized_claim_id, right_normalized_claim_id, retrieval_method,
            retrieval_score, retrieval_query, retrieval_revision)
           VALUES (?, ?, 'test', 1, 'merge', 'merge-v1')""",
        (claim_ids[1], claim_ids[2]),
    )
    await db.commit()
    decision = await client.post(
        f"/api/v2/claim-consolidation/candidates/{cursor.lastrowid}/decisions",
        json={
            "decision": "equivalent", "rationale": "Reviewed cross-group entailment",
            "decider_revision": "human-v2", "confidence": 1,
            "actor": "reviewer@example.test", "compared_qualifiers": {},
        },
    )
    assert decision.status_code == 201
    active_group_id = decision.json()["canonical_group_id"]
    active = (await client.get(
        f"/api/v2/claim-consolidation/groups/{active_group_id}"
    )).json()
    assert {member["normalized_claim_id"] for member in active["members"]
            if member["retired_at"] is None} == set(claim_ids)
    retired_memberships = (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claim_canonical_memberships WHERE retired_at IS NOT NULL"
    )).fetchone())["n"]
    assert retired_memberships == 2


async def test_conflicting_group_merge_rolls_back_human_decision(
    client, extraction_payload
):
    from backend.database import get_db

    first_occurrence, first_claim = await _ingest_claim(
        client, extraction_payload, run=41,
        text="RHOAI 3.5 includes an rhai-cli component in its inventory.",
        version="3.5",
    )
    second_occurrence, second_claim = await _ingest_claim(
        client, extraction_payload, run=42,
        text="The RHOAI 3.5 inventory includes rhai-cli.", version="3.5",
    )
    third_occurrence, third_claim = await _ingest_claim(
        client, extraction_payload, run=43,
        text="RHOAI 3.6 includes an rhai-cli component in its inventory.",
        version="3.6",
    )
    fourth_occurrence, fourth_claim = await _ingest_claim(
        client, extraction_payload, run=44,
        text="The RHOAI 3.6 inventory includes rhai-cli.", version="3.6",
    )
    assert {first_occurrence, second_occurrence, third_occurrence, fourth_occurrence}

    first_group = await client.post("/api/v2/claim-consolidation/groups", json={
        "canonical_text": "RHOAI 3.5 inventory includes rhai-cli",
        "normalized_claim_ids": [first_claim, second_claim],
        "policy_revision": "human-v1", "actor": "reviewer@example.test",
    })
    second_group = await client.post("/api/v2/claim-consolidation/groups", json={
        "canonical_text": "RHOAI 3.6 inventory includes rhai-cli",
        "normalized_claim_ids": [third_claim, fourth_claim],
        "policy_revision": "human-v1", "actor": "reviewer@example.test",
    })
    assert first_group.status_code == second_group.status_code == 201

    db = await get_db()
    candidate = await db.execute(
        """INSERT INTO claim_similarity_candidates
           (left_normalized_claim_id, right_normalized_claim_id, retrieval_method,
            retrieval_score, retrieval_query, retrieval_revision)
           VALUES (?, ?, 'test', 1, 'conflict', 'merge-v1')""",
        (second_claim, third_claim),
    )
    await db.commit()
    response = await client.post(
        f"/api/v2/claim-consolidation/candidates/{candidate.lastrowid}/decisions",
        json={
            "decision": "equivalent", "rationale": "Reviewer tried an invalid merge.",
            "decider_revision": "human-v2", "confidence": 1,
            "actor": "reviewer@example.test", "compared_qualifiers": {},
        },
    )
    assert response.status_code == 409
    assert "compatibility" in response.json()["detail"]
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claim_equivalence_decisions WHERE candidate_id = ?",
        (candidate.lastrowid,),
    )).fetchone())["n"] == 0
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claim_canonical_memberships WHERE retired_at IS NULL"
    )).fetchone())["n"] == 4
    assert (await (await db.execute(
        "SELECT COUNT(*) AS n FROM claim_canonical_groups WHERE retired_at IS NULL"
    )).fetchone())["n"] == 2


async def test_evaluated_policy_can_assign_and_retire_automatic_group(client):
    from backend.database import get_db

    db = await get_db()
    claim_ids = []
    for index in range(2):
        cursor = await db.execute(
            "INSERT INTO claims (claim_text, claim_type, claim_hash) VALUES (?, ?, ?)",
            (f"automatic equivalent claim {index}", "factual", f"auto-hash-{index}"),
        )
        claim_ids.append(cursor.lastrowid)
    candidate = await db.execute(
        """INSERT INTO claim_similarity_candidates
           (left_normalized_claim_id, right_normalized_claim_id, retrieval_method,
            retrieval_score, retrieval_query, retrieval_revision, status)
           VALUES (?, ?, 'evaluated-model', 1, 'automatic', 'model-v1', 'decided')""",
        claim_ids,
    )
    decision = await db.execute(
        """INSERT INTO claim_equivalence_decisions
           (candidate_id, decision, rationale, compared_qualifiers, decider_type,
            decider_revision, confidence)
           VALUES (?, 'equivalent', 'Evaluated mutual entailment', '{}',
                   'model', 'model-policy-v1', 1)""",
        (candidate.lastrowid,),
    )
    assert decision.lastrowid
    await db.commit()

    missing_evaluation = await client.put(
        "/api/v2/claim-consolidation/policies/automatic-missing-eval", json={
            "revision": "automatic-missing-eval",
            "automatic_assignment_enabled": True,
            "kill_switch": False,
            "minimum_confidence": 0.99,
            "minimum_precision": 0.99,
            "evaluated_precision": 1,
            "labeled_dataset_revision": "representative-evaluation-v1",
            "evaluation_run_id": "not-recorded",
        },
    )
    assert missing_evaluation.status_code == 409

    evaluation = await client.post("/api/v2/claim-consolidation/evaluations", json={
        "evaluation_run_id": "representative-eval-run-1",
        "labeled_dataset_revision": "representative-evaluation-v1",
        "retrieval_revision": "model-v1",
        "decision_revision": "model-policy-v1",
        "candidate_count": 4,
        "labeled_pair_count": 4,
        "equivalent_prediction_count": 2,
        "true_positive_count": 2,
        "false_positive_count": 0,
        "false_negative_count": 1,
        "precision": 1,
        "recall": 2 / 3,
        "false_merge_rate": 0,
        "drift_summary": {"artifact_type": {"strategy": 0.0}},
    })
    assert evaluation.status_code == 201, evaluation.text
    assert evaluation.json()["precision"] == 1
    evaluations = await client.get("/api/v2/claim-consolidation/evaluations")
    assert evaluations.status_code == 200
    assert evaluations.json()["evaluations"][0]["evaluation_run_id"] == (
        "representative-eval-run-1"
    )

    policy = await client.put("/api/v2/claim-consolidation/policies/automatic-v1", json={
        "revision": "automatic-v1",
        "automatic_assignment_enabled": True,
        "kill_switch": False,
        "minimum_confidence": 0.99,
        "minimum_precision": 0.99,
        "evaluated_precision": 1,
        "labeled_dataset_revision": "representative-evaluation-v1",
        "evaluation_run_id": "representative-eval-run-1",
    })
    assert policy.status_code == 200, policy.text
    automatic = await client.post(
        "/api/v2/claim-consolidation/automatic/automatic-v1"
    )
    assert automatic.status_code == 200
    assert automatic.json()["assigned"] == 1

    groups = await client.get("/api/v2/claim-consolidation/groups")
    assert groups.status_code == 200
    group_id = groups.json()["groups"][0]["id"]
    summary = await client.get("/api/v2/claim-consolidation/summary")
    assert summary.status_code == 200
    assert summary.json()["canonical_group_count"] == 1
    metrics = await client.get("/api/v2/claim-consolidation/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["overall"]["grouped_text_identity_count"] == 2
    assert metrics.json()["latest_evaluation"]["evaluation_run_id"] == (
        "representative-eval-run-1"
    )
    assert "artifact_type" in metrics.json()["breakdowns"]

    retired = await client.post(
        f"/api/v2/claim-consolidation/groups/{group_id}/retire",
        json={"actor": "operator@example.test", "rationale": "Incorrect merge correction"},
    )
    assert retired.status_code == 200
    assert retired.json()["retired"] is True
    metrics_after_retire = await client.get("/api/v2/claim-consolidation/metrics")
    assert metrics_after_retire.json()["corrections"][
        "retired_memberships_by_actor"
    ][0]["retired_membership_count"] == 2
