"""Tests for chat tool handlers migrated to Claim Assurance v2."""

import json

import aiosqlite
import pytest


@pytest.fixture
async def db(tmp_db):
    """Return a live aiosqlite connection from the tmp_db fixture."""
    from backend.database import get_db
    db = await get_db()
    yield db


async def _seed_v2_data(db: aiosqlite.Connection):
    """Seed a minimal Claim Assurance v2 dataset for chat tool tests.

    Creates:
    - Two extraction runs in different pipelines
    - Two distinct occurrences with identical normalized claim text
    - Multiple verification runs for occurrence 1 (supported then contradicted)
    - An explanation run on the effective verification of occurrence 1
    - A human override on occurrence 1
    - Occurrence 2 is left pending (no verification)
    - A legacy claim/verdict that must not surface in v2 results
    """
    # Normalized claim (shared text identity)
    await db.execute(
        "INSERT INTO claims (id, claim_text, claim_type, claim_hash) VALUES (?, ?, ?, ?)",
        (1, "RHOAI ships model serving.", "factual", "hash-a"),
    )

    # Extraction run 1 (pipeline: rfe-reviews)
    await db.execute(
        """INSERT INTO claim_extraction_runs
           (id, run_key, source_file, pipeline_slug, artifact_type,
            extractor_revision, status, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (1, "run-1", "artifacts/RHAIRFE-1/review.md", "rfe-reviews",
         "rfe-review", "extract@v1", "complete"),
    )
    # Source unit 1
    await db.execute(
        """INSERT INTO claim_source_units
           (id, extraction_run_id, unit_key, unit_kind, source_locator, original_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (1, 1, "unit-1", "sentence", "review.md:10",
         "RHOAI ships model serving."),
    )
    # Occurrence 1 (from extraction run 1)
    await db.execute(
        """INSERT INTO claim_occurrences
           (id, normalized_claim_id, source_unit_id, claim_text, claim_type,
            accepted, occurrence_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (111, 1, 1, "RHOAI ships model serving.", "factual", 1, "occ-hash-1"),
    )
    await db.execute(
        "INSERT INTO claim_occurrence_jira_keys (claim_occurrence_id, jira_key) VALUES (?, ?)",
        (111, "RHAIRFE-1"),
    )

    # Extraction run 2 (pipeline: end-to-end)
    await db.execute(
        """INSERT INTO claim_extraction_runs
           (id, run_key, source_file, pipeline_slug, artifact_type,
            extractor_revision, status, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (2, "run-2", "artifacts/RHAIRFE-2/strategy.md", "end-to-end",
         "strategy", "extract@v1", "complete"),
    )
    # Source unit 2
    await db.execute(
        """INSERT INTO claim_source_units
           (id, extraction_run_id, unit_key, unit_kind, source_locator, original_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (2, 2, "unit-2", "sentence", "strategy.md:5",
         "RHOAI ships model serving."),
    )
    # Occurrence 2 (same normalized text, different source — pending)
    await db.execute(
        """INSERT INTO claim_occurrences
           (id, normalized_claim_id, source_unit_id, claim_text, claim_type,
            accepted, occurrence_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (208, 1, 2, "RHOAI ships model serving.", "factual", 1, "occ-hash-2"),
    )
    await db.execute(
        "INSERT INTO claim_occurrence_jira_keys (claim_occurrence_id, jira_key) VALUES (?, ?)",
        (208, "RHAIRFE-2"),
    )

    # Verification run 1 for occurrence 111 (older, supported)
    await db.execute(
        """INSERT INTO claim_verification_runs
           (id, claim_occurrence_id, verifier_revision, verdict, confidence,
            severity, evidence_summary, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-1 hour'))""",
        (660, 111, "verify@v1", "supported", 0.9, "low",
         "Evidence supports the claim.", "test-model"),
    )

    # Verification run 2 for occurrence 111 (newer, contradicted — effective)
    await db.execute(
        """INSERT INTO claim_verification_runs
           (id, claim_occurrence_id, verifier_revision, verdict, confidence,
            severity, evidence_summary, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (667, 111, "verify@v2", "contradicted", 0.85, "high",
         "New evidence contradicts the claim.", "test-model"),
    )

    # Evidence record for the effective verification
    await db.execute(
        """INSERT INTO claim_evidence_records
           (stage, stage_run_id, evidence_type, relationship, uri, source_locator)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("verification", 667, "document", "contradicts",
         "artifact://architecture-context/serving.md", "serving.md:42"),
    )

    # Explanation run on the effective verification of occurrence 111
    await db.execute(
        """INSERT INTO claim_explanation_runs
           (id, verification_run_id, explainer_revision, category,
            improvement_target, explanation, contributing_factors,
            alternative_explanations, remediation, regression_test,
            human_review_required, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (770, 667, "explain@v1", "stale_context", "context_retrieval",
         "The architecture doc was updated after extraction.",
         '["doc lag", "caching"]', '["model error"]',
         "Re-index architecture context.", "re-run verification after reindex",
         0),
    )

    # Evidence record for the explanation
    await db.execute(
        """INSERT INTO claim_evidence_records
           (stage, stage_run_id, evidence_type, relationship, uri, source_locator)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("explanation", 770, "document", "supports",
         "artifact://architecture-context/serving.md", "serving.md:1"),
    )

    # Human override on occurrence 111, bound to the effective verification
    await db.execute(
        """INSERT INTO claim_human_overrides
           (id, claim_occurrence_id, verification_run_id, actor, decision, rationale)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (1, 111, 667, "reviewer@example.com", "accepted",
         "Confirmed contradiction; context was stale."),
    )

    # Legacy claim/verdict that must NOT appear in v2 chat results
    await db.execute(
        "INSERT INTO claims (id, claim_text, claim_type, claim_hash) VALUES (?, ?, ?, ?)",
        (99, "Legacy claim text.", "factual", "hash-legacy"),
    )
    await db.execute(
        """INSERT INTO claim_sources (claim_id, source_file, pipeline_slug)
           VALUES (?, ?, ?)""",
        (99, "old-source.md", "legacy-pipeline"),
    )
    await db.execute(
        """INSERT INTO claim_verdicts (claim_id, verdict, confidence, evidence_summary)
           VALUES (?, ?, ?, ?)""",
        (99, "refuted", 0.7, "Legacy refuted."),
    )

    await db.commit()


# --- query_claims tests ---


async def test_query_claims_returns_both_duplicate_occurrences(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"search": "model serving"}))
    assert result["data_authority"] == "claim_assurance_v2"
    ids = [occ["occurrence_id"] for occ in result["occurrences"]]
    assert 111 in ids
    assert 208 in ids
    assert len(result["occurrences"]) == 2


async def test_query_claims_exact_occurrence_lookup(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"occurrence_id": 208}))
    assert len(result["occurrences"]) == 1
    occ = result["occurrences"][0]
    assert occ["occurrence_id"] == 208
    assert occ["effective_verdict"] == "pending"


async def test_query_claims_canonical_verdicts(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"verdict": "contradicted"}))
    assert all(
        occ["effective_verdict"] == "contradicted" for occ in result["occurrences"]
    )
    assert any(occ["occurrence_id"] == 111 for occ in result["occurrences"])


async def test_query_claims_pending_means_no_verification(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"verdict": "pending"}))
    assert len(result["occurrences"]) == 1
    occ = result["occurrences"][0]
    assert occ["occurrence_id"] == 208
    assert occ["effective_verdict"] == "pending"
    assert occ["effective_verification_run_id"] is None


async def test_query_claims_pipeline_filter(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "query_claims", {"pipeline_slug": "rfe-reviews"},
    ))
    assert len(result["occurrences"]) == 1
    assert result["occurrences"][0]["occurrence_id"] == 111
    assert result["occurrences"][0]["pipeline_slug"] == "rfe-reviews"


async def test_query_claims_jira_filter(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "query_claims", {"jira_key": "RHAIRFE-2"},
    ))
    assert len(result["occurrences"]) == 1
    assert result["occurrences"][0]["occurrence_id"] == 208


async def test_query_claims_includes_ui_path(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"occurrence_id": 111}))
    assert result["occurrences"][0]["ui_path"] == "/hallucinations?occurrence=111"


async def test_query_claims_legacy_records_excluded(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(db, "query_claims", {"search": "Legacy claim"}))
    assert result["total"] == 0
    assert len(result["occurrences"]) == 0


# --- get_claim_occurrence_history tests ---


async def test_history_effective_ids(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 111},
    ))
    assert result["data_authority"] == "claim_assurance_v2"
    assert result["effective_verification_run_id"] == 667
    assert result["effective_explanation_run_id"] == 770


async def test_history_retains_old_runs(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 111},
    ))
    runs = result["verification_runs"]
    assert len(runs) == 2
    older = next(r for r in runs if r["id"] == 660)
    assert older["verdict"] == "supported"
    assert older["is_effective"] is False
    effective = next(r for r in runs if r["id"] == 667)
    assert effective["verdict"] == "contradicted"
    assert effective["is_effective"] is True


async def test_history_includes_evidence(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 111},
    ))
    effective = next(r for r in result["verification_runs"] if r["is_effective"])
    assert len(effective["evidence"]) >= 1
    assert effective["evidence"][0]["relationship"] == "contradicts"


async def test_history_explanation_with_structured_fields(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 111},
    ))
    effective_v = next(r for r in result["verification_runs"] if r["is_effective"])
    assert len(effective_v["explanation_runs"]) == 1
    exp = effective_v["explanation_runs"][0]
    assert exp["id"] == 770
    assert exp["is_effective"] is True
    assert exp["category"] == "stale_context"
    assert exp["improvement_target"] == "context_retrieval"
    assert exp["remediation"] is not None
    assert len(exp["contributing_factors"]) == 2
    assert len(exp["alternative_explanations"]) == 1


async def test_history_overrides_separate_from_verdict(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 111},
    ))
    assert len(result["human_overrides"]) == 1
    override = result["human_overrides"][0]
    assert override["verification_run_id"] == 667
    assert override["decision"] == "accepted"
    # The effective verdict is still the factual one, not the override
    effective_v = next(r for r in result["verification_runs"] if r["is_effective"])
    assert effective_v["verdict"] == "contradicted"


async def test_history_unknown_occurrence(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 99999},
    ))
    assert "error" in result
    assert "99999" in result["error"]


async def test_history_pending_occurrence(db):
    """Occurrence 208 has no verification runs — verified_without_explanation state."""
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_occurrence_history", {"occurrence_id": 208},
    ))
    assert result["effective_verification_run_id"] is None
    assert result["effective_explanation_run_id"] is None
    assert result["processing_state"] == "not_verified"
    assert len(result["verification_runs"]) == 0


# --- query_claim_explanations tests ---


async def test_query_explanations_returns_v2_data(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "query_claim_explanations", {},
    ))
    assert result["data_authority"] == "claim_assurance_v2"
    assert result["total"] >= 1
    exp = result["explanations"][0]
    assert exp["category"] == "stale_context"
    assert exp["improvement_target"] == "context_retrieval"
    assert "occurrence_id" in exp


async def test_query_explanations_category_filter(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "query_claim_explanations", {"category": "nonexistent_category"},
    ))
    assert result["total"] == 0
    assert len(result["explanations"]) == 0


# --- get_claim_assurance_summary tests ---


async def test_summary_effective_counts(db):
    await _seed_v2_data(db)
    from backend.chat.tools import execute_tool

    result = json.loads(await execute_tool(
        db, "get_claim_assurance_summary", {},
    ))
    assert result["data_authority"] == "claim_assurance_v2"
    assert result["label"] == "effective_occurrence_summary"
    assert result["total_occurrences"] == 2
    assert result["verdicts"]["contradicted"] == 1
    assert result["pending"] == 1


# --- Tool definition contract tests ---


def _has_standalone_legacy_verdict(text: str) -> str | None:
    """Check for legacy verdict names not part of canonical v2 verdicts."""
    import re
    for legacy in ("refuted", "inconclusive"):
        if re.search(rf"\b{legacy}\b", text, re.IGNORECASE):
            return legacy
    # "insufficient" alone (not "insufficient_evidence") is legacy
    for match in re.finditer(r"\binsufficient\b", text, re.IGNORECASE):
        following = text[match.end():match.end() + 10]
        if not following.startswith("_evidence"):
            return "insufficient"
    return None


def test_tool_definitions_use_v2_vocabulary():
    from backend.chat.tools import TOOL_DEFINITIONS

    claims_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "query_claims")
    desc = claims_tool["description"]
    assert "occurrence" in desc.lower()
    assert "claim_assurance" in desc.lower() or "Claim Assurance" in desc

    verdict_prop = claims_tool["input_schema"]["properties"]["verdict"]
    canonical = {"supported", "contradicted", "insufficient_evidence", "not_applicable", "pending"}
    assert set(verdict_prop["enum"]) == canonical

    legacy = _has_standalone_legacy_verdict(desc)
    assert legacy is None, f"Legacy verdict '{legacy}' in tool description"


def test_tool_definitions_include_new_tools():
    from backend.chat.tools import TOOL_DEFINITIONS

    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "get_claim_occurrence_history" in names
    assert "query_claim_explanations" in names
    assert "get_claim_assurance_summary" in names


def test_system_prompt_contains_v2_semantics():
    from backend.chat.agent import _BASE_SYSTEM_PROMPT

    assert "Claim Assurance v2" in _BASE_SYSTEM_PROMPT
    assert "occurrence" in _BASE_SYSTEM_PROMPT
    assert "effective" in _BASE_SYSTEM_PROMPT.lower()
    assert "Human overrides" in _BASE_SYSTEM_PROMPT or "override" in _BASE_SYSTEM_PROMPT.lower()
    legacy = _has_standalone_legacy_verdict(_BASE_SYSTEM_PROMPT)
    assert legacy is None, f"Legacy verdict '{legacy}' in system prompt"
