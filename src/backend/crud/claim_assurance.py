import hashlib
import json
import re

import aiosqlite

from backend.schemas.claim_assurance import (
    EvidenceRecord,
    ExplanationRunInput,
    ExtractionRunInput,
    HumanOverrideInput,
    RegressionRunInput,
    StageReceiptEventInput,
    VerificationRunInput,
)


class ExtractionRunConflict(Exception):
    """A supposedly idempotent run key was reused for different content."""


JIRA_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,20}-\d+\b")


def _extract_jira_keys(value: str) -> set[str]:
    return {match.group(0).upper() for match in JIRA_KEY_PATTERN.finditer(value)}


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _coverage_metrics(values: dict) -> dict:
    """Calculate both class F1 scores from element-level coverage decisions."""
    result = dict(values)
    verifiable_covered = result.get("verifiable_covered", 0)
    verifiable_omitted = result.get("verifiable_omitted", 0)
    unverifiable_omitted = result.get("unverifiable_omitted", 0)
    unverifiable_included = result.get("unverifiable_included", 0)

    verifiable_precision = (
        verifiable_covered / (verifiable_covered + unverifiable_included)
        if verifiable_covered + unverifiable_included else None
    )
    verifiable_recall = (
        verifiable_covered / (verifiable_covered + verifiable_omitted)
        if verifiable_covered + verifiable_omitted else None
    )
    unverifiable_precision = (
        unverifiable_omitted / (unverifiable_omitted + verifiable_omitted)
        if unverifiable_omitted + verifiable_omitted else None
    )
    unverifiable_recall = (
        unverifiable_omitted / (unverifiable_omitted + unverifiable_included)
        if unverifiable_omitted + unverifiable_included else None
    )

    def f1(precision, recall):
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    verifiable_f1 = f1(verifiable_precision, verifiable_recall)
    unverifiable_f1 = f1(unverifiable_precision, unverifiable_recall)
    result.update({
        "verifiable_element_precision": verifiable_precision,
        "verifiable_element_recall": verifiable_recall,
        "verifiable_element_f1": verifiable_f1,
        "unverifiable_element_precision": unverifiable_precision,
        "unverifiable_element_recall": unverifiable_recall,
        "unverifiable_element_f1": unverifiable_f1,
        "element_macro_f1": (
            (verifiable_f1 + unverifiable_f1) / 2
            if verifiable_f1 is not None and unverifiable_f1 is not None else None
        ),
        "explicit_unverifiable_element_inclusion_rate": (
            unverifiable_included /
            (unverifiable_omitted + unverifiable_included)
            if unverifiable_omitted + unverifiable_included else None
        ),
    })
    return result


async def _store_evidence(
    db: aiosqlite.Connection,
    stage: str,
    stage_run_id: int,
    records: list[EvidenceRecord],
) -> None:
    for record in records:
        await db.execute(
            """INSERT INTO claim_evidence_records
               (stage, stage_run_id, evidence_type, uri, repository_revision,
                artifact_digest, source_locator, query, excerpt, relationship,
                authority, product_version, retrieved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (stage, stage_run_id, *record.model_dump().values()),
        )


async def create_extraction_run(db: aiosqlite.Connection, data: ExtractionRunInput) -> dict:
    payload_digest = hashlib.sha256(
        json.dumps(
            data.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    existing = await db.execute(
        "SELECT id, payload_digest FROM claim_extraction_runs WHERE run_key = ?",
        (data.run_key,),
    )
    if row := await existing.fetchone():
        if row["payload_digest"] and row["payload_digest"] != payload_digest:
            raise ExtractionRunConflict(
                f"run_key {data.run_key!r} already identifies a different payload"
            )
        return {"id": row["id"], "created": False}

    cursor = await db.execute(
        """INSERT INTO claim_extraction_runs
           (run_key, payload_digest, source_file, pipeline_slug, artifact_type, artifact_digest,
            extractor_revision, repository_revision,
            model, harness, configuration_digest, configuration, token_count,
            cost_usd, duration_seconds, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
        (
            data.run_key, payload_digest, data.source_file, data.pipeline_slug,
            data.artifact_type or data.pipeline_slug, data.artifact_digest,
            data.extractor_revision, data.repository_revision, data.model, data.harness,
            data.configuration_digest, json.dumps(data.configuration, sort_keys=True),
            data.token_count, data.cost_usd, data.duration_seconds,
        ),
    )
    run_id = cursor.lastrowid
    source_jira_keys = _extract_jira_keys(data.source_file)
    occurrence_ids: list[int] = []
    for unit in data.units:
        source = unit.source_unit
        cursor = await db.execute(
            """INSERT INTO claim_source_units
               (extraction_run_id, unit_key, unit_kind, source_locator, original_text,
                heading_path, preceding_context, following_context, list_preamble)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, source.unit_key, source.unit_kind, source.source_locator,
                source.original_text, json.dumps(source.heading_path),
                json.dumps(source.preceding_context), json.dumps(source.following_context),
                source.list_preamble,
            ),
        )
        unit_id = cursor.lastrowid
        selection = unit.selection
        await db.execute(
            """INSERT INTO claim_selection_results
               (source_unit_id, classification, selected_text, rationale, evaluator_revision)
               VALUES (?, ?, ?, ?, ?)""",
            (unit_id, selection.classification, selection.selected_text,
             selection.rationale, selection.evaluator_revision),
        )
        if unit.ambiguity:
            ambiguity = unit.ambiguity
            await db.execute(
                """INSERT INTO claim_ambiguity_results
                   (source_unit_id, status, ambiguity_types, clarified_text,
                    resolution_context, rationale, evaluator_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (unit_id, ambiguity.status, json.dumps(ambiguity.ambiguity_types),
                 ambiguity.clarified_text, json.dumps(ambiguity.resolution_context),
                 ambiguity.rationale, ambiguity.evaluator_revision),
            )
        for claim in unit.claims:
            claim_hash = _digest(claim.claim_text)
            await db.execute(
                """INSERT OR IGNORE INTO claims (claim_text, claim_type, claim_hash)
                   VALUES (?, ?, ?)""",
                (claim.claim_text, claim.claim_type, claim_hash),
            )
            claim_cursor = await db.execute(
                "SELECT id FROM claims WHERE claim_hash = ?", (claim_hash,)
            )
            claim_id = (await claim_cursor.fetchone())["id"]
            occurrence_hash = _digest(f"{run_id}:{source.unit_key}:{claim.claim_text}")
            cursor = await db.execute(
                """INSERT INTO claim_occurrences
                   (normalized_claim_id, source_unit_id, claim_text, original_text,
                    claim_type, modality, product_version, temporal_scope,
                    clarification, accepted, occurrence_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (claim_id, unit_id, claim.claim_text, claim.original_text,
                 claim.claim_type, claim.modality, claim.product_version,
                 claim.temporal_scope, claim.clarification, claim.accepted,
                 occurrence_hash),
            )
            occurrence_id = cursor.lastrowid
            occurrence_ids.append(occurrence_id)
            jira_keys = source_jira_keys | {
                jira_key.upper() for jira_key in claim.jira_keys
            }
            for jira_key in sorted(jira_keys):
                await db.execute(
                    "INSERT OR IGNORE INTO claim_jira_keys (claim_id, jira_key) VALUES (?, ?)",
                    (claim_id, jira_key),
                )
                await db.execute(
                    """INSERT OR IGNORE INTO claim_occurrence_jira_keys
                       (claim_occurrence_id, jira_key) VALUES (?, ?)""",
                    (occurrence_id, jira_key),
                )
            if claim.evaluation:
                evaluation = claim.evaluation
                evaluation_cursor = await db.execute(
                    """INSERT INTO claim_extraction_evaluations
                       (claim_occurrence_id, evaluator_revision, entailed,
                        entailment_rationale, coverage_result,
                        decontextualization_result, maximally_contextualized_claim,
                        extracted_retrieval_digest, comparison_retrieval_digest,
                        evidence_context_digest)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (occurrence_id, evaluation.evaluator_revision, evaluation.entailed,
                     evaluation.entailment_rationale, evaluation.coverage_result,
                     evaluation.decontextualization_result,
                     evaluation.maximally_contextualized_claim,
                     evaluation.extracted_retrieval_digest,
                     evaluation.comparison_retrieval_digest,
                     evaluation.evidence_context_digest),
                )
                for element in evaluation.coverage_elements:
                    await db.execute(
                        """INSERT INTO claim_coverage_elements
                           (extraction_evaluation_id, element_text, element_kind,
                            coverage, rationale) VALUES (?, ?, ?, ?, ?)""",
                        (evaluation_cursor.lastrowid, element.element_text,
                         element.element_kind, element.coverage, element.rationale),
                    )
                await _store_evidence(
                    db, "extraction", evaluation_cursor.lastrowid, evaluation.evidence
                )
    await db.execute(
        "UPDATE claim_extraction_runs SET status = 'complete', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (run_id,),
    )
    await db.commit()
    return {"id": run_id, "created": True, "occurrence_ids": occurrence_ids}


async def create_verification_run(db: aiosqlite.Connection, data: VerificationRunInput) -> dict:
    cursor = await db.execute(
        """INSERT INTO claim_verification_runs
            (claim_occurrence_id, verifier_revision, repository_revision, model,
            harness, configuration_digest, evidence_context_digest, verdict, severity,
            confidence, evidence_summary, token_count, cost_usd, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.claim_occurrence_id, data.verifier_revision,
            data.repository_revision, data.model, data.harness, data.configuration_digest,
            data.evidence_context_digest, data.verdict, data.severity,
            data.confidence, data.evidence_summary, data.token_count,
            data.cost_usd, data.duration_seconds,
        ),
    )
    run_id = cursor.lastrowid
    await _store_evidence(db, "verification", run_id, data.evidence)
    await db.commit()
    return {"id": run_id}


async def create_explanation_run(db: aiosqlite.Connection, data: ExplanationRunInput) -> dict:
    cursor = await db.execute(
        """INSERT INTO claim_explanation_runs
           (verification_run_id, explainer_revision, repository_revision, model,
            harness, configuration_digest, category, improvement_target, explanation,
            contributing_factors, alternative_explanations, remediation,
            regression_test, human_review_required, token_count, cost_usd,
            duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.verification_run_id, data.explainer_revision,
         data.repository_revision, data.model,
         data.harness, data.configuration_digest, data.category,
         data.improvement_target, data.explanation,
         json.dumps(data.contributing_factors), json.dumps(data.alternative_explanations),
         data.remediation, data.regression_test, data.human_review_required,
         data.token_count, data.cost_usd, data.duration_seconds),
    )
    run_id = cursor.lastrowid
    await _store_evidence(db, "explanation", run_id, data.evidence)
    await db.commit()
    return {"id": run_id}


async def get_occurrence_history(db: aiosqlite.Connection, occurrence_id: int) -> dict | None:
    cursor = await db.execute(
        """SELECT co.*, c.claim_hash, csu.source_locator, cer.run_key
           FROM claim_occurrences co
           JOIN claims c ON c.id = co.normalized_claim_id
           JOIN claim_source_units csu ON csu.id = co.source_unit_id
           JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
           WHERE co.id = ?""",
        (occurrence_id,),
    )
    occurrence = await cursor.fetchone()
    if not occurrence:
        return None
    cursor = await db.execute(
        "SELECT * FROM claim_verification_runs WHERE claim_occurrence_id = ? ORDER BY id",
        (occurrence_id,),
    )
    verification_runs = [dict(row) for row in await cursor.fetchall()]
    for verification in verification_runs:
        evidence_cursor = await db.execute(
            """SELECT * FROM claim_evidence_records
               WHERE stage = 'verification' AND stage_run_id = ? ORDER BY id""",
            (verification["id"],),
        )
        verification["evidence"] = [dict(row) for row in await evidence_cursor.fetchall()]
        explanation_cursor = await db.execute(
            "SELECT * FROM claim_explanation_runs WHERE verification_run_id = ? ORDER BY id",
            (verification["id"],),
        )
        verification["explanation_runs"] = [
            dict(row) for row in await explanation_cursor.fetchall()
        ]
        for explanation in verification["explanation_runs"]:
            evidence_cursor = await db.execute(
                """SELECT * FROM claim_evidence_records
                   WHERE stage = 'explanation' AND stage_run_id = ? ORDER BY id""",
                (explanation["id"],),
            )
            explanation["evidence"] = [
                dict(row) for row in await evidence_cursor.fetchall()
            ]
            regression_cursor = await db.execute(
                "SELECT * FROM claim_regression_runs WHERE explanation_run_id = ? ORDER BY id",
                (explanation["id"],),
            )
            explanation["regression_runs"] = [
                dict(row) for row in await regression_cursor.fetchall()
            ]
    override_cursor = await db.execute(
        "SELECT * FROM claim_human_overrides WHERE claim_occurrence_id = ? ORDER BY id",
        (occurrence_id,),
    )
    return {
        "occurrence": dict(occurrence),
        "verification_runs": verification_runs,
        "human_overrides": [dict(row) for row in await override_cursor.fetchall()],
    }


async def get_effective_verdict(db: aiosqlite.Connection, occurrence_id: int) -> dict | None:
    """Return the newest verdict; history is immutable and remains authoritative."""
    cursor = await db.execute(
        """SELECT * FROM claim_verification_runs
           WHERE claim_occurrence_id = ?
           ORDER BY created_at DESC, id DESC LIMIT 1""",
        (occurrence_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _get_assurance_breakdowns(db: aiosqlite.Connection) -> dict:
    """Return comparable metrics keyed by artifact and resolved implementation."""
    cursor = await db.execute(
        """SELECT
             COALESCE(cer.artifact_type, cer.pipeline_slug) AS artifact_type,
             cer.extractor_revision,
             COALESCE(cer.model, '') AS model,
             COALESCE(cer.harness, '') AS harness,
             COALESCE(cer.configuration_digest, '') AS configuration_digest,
             COUNT(DISTINCT cer.id) AS extraction_runs,
             COUNT(DISTINCT csu.id) AS source_units,
             COUNT(DISTINCT co.id) AS occurrences,
             COUNT(DISTINCT CASE WHEN co.accepted = 1 THEN co.id END)
               AS accepted_occurrences,
             COUNT(DISTINCT CASE WHEN cee.entailed = 1 THEN co.id END)
               AS entailed_occurrences,
             COUNT(DISTINCT CASE WHEN cee.entailed = 0 THEN co.id END)
               AS non_entailed_occurrences,
             COUNT(DISTINCT CASE WHEN car.status = 'unresolved' THEN csu.id END)
               AS unresolved_units,
             COUNT(DISTINCT CASE WHEN cee.decontextualization_result IS NOT NULL
                                  THEN cee.id END) AS decontextualization_total,
             COUNT(DISTINCT CASE WHEN cee.decontextualization_result IN
                                      ('desirable', 'self_contained')
                                  THEN cee.id END) AS desirable_decontextualization
           FROM claim_extraction_runs cer
           LEFT JOIN claim_source_units csu ON csu.extraction_run_id = cer.id
           LEFT JOIN claim_ambiguity_results car ON car.source_unit_id = csu.id
           LEFT JOIN claim_occurrences co ON co.source_unit_id = csu.id
           LEFT JOIN claim_extraction_evaluations cee ON cee.claim_occurrence_id = co.id
           GROUP BY artifact_type, cer.extractor_revision, model, harness,
                    configuration_digest
           ORDER BY artifact_type, cer.extractor_revision, model,
                    configuration_digest"""
    )
    extraction = [dict(row) for row in await cursor.fetchall()]

    def key(row):
        return (
            row["artifact_type"], row["extractor_revision"], row["model"],
            row["harness"], row["configuration_digest"],
        )

    cursor = await db.execute(
        """SELECT
             COALESCE(cer.artifact_type, cer.pipeline_slug) AS artifact_type,
             cer.extractor_revision,
             COALESCE(cer.model, '') AS model,
             COALESCE(cer.harness, '') AS harness,
             COALESCE(cer.configuration_digest, '') AS configuration_digest,
             COALESCE(SUM(CASE WHEN cce.element_kind = 'verifiable'
                                AND cce.coverage IN ('explicit', 'implicit')
                               THEN 1 ELSE 0 END), 0) AS verifiable_covered,
             COALESCE(SUM(CASE WHEN cce.element_kind = 'verifiable'
                                AND cce.coverage = 'omitted'
                               THEN 1 ELSE 0 END), 0) AS verifiable_omitted,
             COALESCE(SUM(CASE WHEN cce.element_kind = 'unverifiable'
                                AND cce.coverage = 'included'
                               THEN 1 ELSE 0 END), 0) AS unverifiable_included,
             COALESCE(SUM(CASE WHEN cce.element_kind = 'unverifiable'
                                AND cce.coverage = 'omitted'
                               THEN 1 ELSE 0 END), 0) AS unverifiable_omitted,
             COALESCE(SUM(CASE WHEN cce.element_kind = 'unverifiable'
                               THEN 1 ELSE 0 END), 0) AS unverifiable_total
           FROM claim_extraction_runs cer
           LEFT JOIN claim_source_units csu ON csu.extraction_run_id = cer.id
           LEFT JOIN claim_occurrences co ON co.source_unit_id = csu.id
           LEFT JOIN claim_extraction_evaluations cee ON cee.claim_occurrence_id = co.id
           LEFT JOIN claim_coverage_elements cce
             ON cce.extraction_evaluation_id = cee.id
           GROUP BY artifact_type, cer.extractor_revision, model, harness,
                    configuration_digest"""
    )
    coverage = {key(dict(row)): _coverage_metrics(dict(row))
                for row in await cursor.fetchall()}
    cursor = await db.execute(
        """SELECT
             COALESCE(artifact_type, pipeline_slug) AS artifact_type,
             extractor_revision, COALESCE(model, '') AS model,
             COALESCE(harness, '') AS harness,
             COALESCE(configuration_digest, '') AS configuration_digest,
             COALESCE(SUM(token_count), 0) AS token_count,
             COALESCE(SUM(cost_usd), 0) AS cost_usd,
             COALESCE(SUM(duration_seconds), 0) AS duration_seconds
           FROM claim_extraction_runs
           GROUP BY artifact_type, extractor_revision, model, harness,
                    configuration_digest"""
    )
    resources = {key(dict(row)): dict(row) for row in await cursor.fetchall()}
    for item in extraction:
        item_key = key(item)
        item["source_entailment_rate"] = (
            item["entailed_occurrences"] / item["occurrences"]
            if item["occurrences"] else None
        )
        item["unresolved_ambiguity_rate"] = (
            item["unresolved_units"] / item["source_units"]
            if item["source_units"] else None
        )
        item["desirable_decontextualization_rate"] = (
            item["desirable_decontextualization"] /
            item["decontextualization_total"]
            if item["decontextualization_total"] else None
        )
        item["coverage"] = coverage.get(item_key, {})
        resource = resources.get(item_key, {})
        item["resource_usage"] = {
            name: resource.get(name, 0)
            for name in ("token_count", "cost_usd", "duration_seconds")
        }

    cursor = await db.execute(
        """SELECT COALESCE(cer.artifact_type, cer.pipeline_slug) AS artifact_type,
                  cvr.verifier_revision, COALESCE(cvr.model, '') AS model,
                  COALESCE(cvr.harness, '') AS harness,
                  COALESCE(cvr.configuration_digest, '') AS configuration_digest,
                  cvr.verdict, COUNT(*) AS count,
                  COALESCE(SUM(cvr.token_count), 0) AS token_count,
                  COALESCE(SUM(cvr.cost_usd), 0) AS cost_usd,
                  COALESCE(SUM(cvr.duration_seconds), 0) AS duration_seconds
           FROM claim_verification_runs cvr
           JOIN claim_occurrences co ON co.id = cvr.claim_occurrence_id
           JOIN claim_source_units csu ON csu.id = co.source_unit_id
           JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
           GROUP BY 1, 2, 3, 4, 5, 6
           ORDER BY 1, 2, 3, 6"""
    )
    verification = [dict(row) for row in await cursor.fetchall()]

    cursor = await db.execute(
        """SELECT COALESCE(cer.artifact_type, cer.pipeline_slug) AS artifact_type,
                  cerx.explainer_revision, COALESCE(cerx.model, '') AS model,
                  COALESCE(cerx.harness, '') AS harness,
                  COALESCE(cerx.configuration_digest, '') AS configuration_digest,
                  cerx.category, COUNT(*) AS count,
                  CAST(COUNT(*) AS REAL) / SUM(COUNT(*)) OVER (
                    PARTITION BY COALESCE(cer.artifact_type, cer.pipeline_slug),
                                 cerx.explainer_revision, COALESCE(cerx.model, ''),
                                 COALESCE(cerx.harness, ''),
                                 COALESCE(cerx.configuration_digest, '')
                  ) AS recurrence_rate,
                  COALESCE(SUM(cerx.token_count), 0) AS token_count,
                  COALESCE(SUM(cerx.cost_usd), 0) AS cost_usd,
                  COALESCE(SUM(cerx.duration_seconds), 0) AS duration_seconds
           FROM claim_explanation_runs cerx
           JOIN claim_verification_runs cvr ON cvr.id = cerx.verification_run_id
           JOIN claim_occurrences co ON co.id = cvr.claim_occurrence_id
           JOIN claim_source_units csu ON csu.id = co.source_unit_id
           JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
           GROUP BY 1, 2, 3, 4, 5, 6
           ORDER BY 1, 2, 3, 6"""
    )
    explanations = [dict(row) for row in await cursor.fetchall()]

    cursor = await db.execute(
        """SELECT stage, skill_revision, COALESCE(model, '') AS model,
                  COALESCE(harness, '') AS harness,
                  COALESCE(configuration_digest, '') AS configuration_digest,
                  status, COUNT(*) AS events,
                  COALESCE(SUM(agent_job_avoided), 0) AS agent_jobs_avoided
           FROM claim_stage_receipt_events
           GROUP BY stage, skill_revision, model, harness,
                    configuration_digest, status
           ORDER BY stage, skill_revision, model, status"""
    )
    receipts = [dict(row) for row in await cursor.fetchall()]
    return {
        "extraction": extraction,
        "verification": verification,
        "explanation": explanations,
        "receipts": receipts,
    }


async def get_assurance_summary(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute(
        """SELECT
             COUNT(DISTINCT cer.id) AS extraction_runs,
             COUNT(DISTINCT csu.id) AS source_units,
             COUNT(DISTINCT co.id) AS occurrences,
             COUNT(DISTINCT CASE WHEN csr.classification = 'unverifiable' THEN csu.id END)
               AS unverifiable_units,
             COUNT(DISTINCT CASE WHEN car.status = 'unresolved' THEN csu.id END)
               AS unresolved_units,
             COUNT(DISTINCT CASE WHEN cee.entailed = 1 THEN co.id END)
               AS entailed_occurrences,
             COUNT(DISTINCT CASE WHEN cee.entailed = 0 THEN co.id END)
               AS non_entailed_occurrences
           FROM claim_extraction_runs cer
           LEFT JOIN claim_source_units csu ON csu.extraction_run_id = cer.id
           LEFT JOIN claim_selection_results csr ON csr.source_unit_id = csu.id
           LEFT JOIN claim_ambiguity_results car ON car.source_unit_id = csu.id
           LEFT JOIN claim_occurrences co ON co.source_unit_id = csu.id
           LEFT JOIN claim_extraction_evaluations cee ON cee.claim_occurrence_id = co.id"""
    )
    result = dict(await cursor.fetchone())
    cursor = await db.execute(
        """SELECT
             (SELECT COALESCE(SUM(token_count), 0) FROM claim_extraction_runs) +
             (SELECT COALESCE(SUM(token_count), 0) FROM claim_verification_runs) +
             (SELECT COALESCE(SUM(token_count), 0) FROM claim_explanation_runs)
               AS token_count,
             (SELECT COALESCE(SUM(cost_usd), 0) FROM claim_extraction_runs) +
             (SELECT COALESCE(SUM(cost_usd), 0) FROM claim_verification_runs) +
             (SELECT COALESCE(SUM(cost_usd), 0) FROM claim_explanation_runs)
               AS cost_usd,
             (SELECT COALESCE(SUM(duration_seconds), 0) FROM claim_extraction_runs) +
             (SELECT COALESCE(SUM(duration_seconds), 0) FROM claim_verification_runs) +
             (SELECT COALESCE(SUM(duration_seconds), 0) FROM claim_explanation_runs)
               AS duration_seconds"""
    )
    result["resource_usage"] = dict(await cursor.fetchone())
    cursor = await db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN element_kind = 'verifiable'
                                AND coverage IN ('explicit', 'implicit') THEN 1 ELSE 0 END), 0)
               AS verifiable_covered,
             COALESCE(SUM(CASE WHEN element_kind = 'verifiable'
                                AND coverage = 'omitted' THEN 1 ELSE 0 END), 0)
               AS verifiable_omitted,
             COALESCE(SUM(CASE WHEN element_kind = 'unverifiable'
                                AND coverage = 'included' THEN 1 ELSE 0 END), 0)
               AS unverifiable_included,
             COALESCE(SUM(CASE WHEN element_kind = 'unverifiable'
                                AND coverage = 'omitted' THEN 1 ELSE 0 END), 0)
               AS unverifiable_omitted,
             COALESCE(SUM(CASE WHEN element_kind = 'unverifiable' THEN 1 ELSE 0 END), 0)
               AS unverifiable_total
           FROM claim_coverage_elements"""
    )
    result["coverage"] = _coverage_metrics(dict(await cursor.fetchone()))
    cursor = await db.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN decontextualization_result IN
                    ('desirable', 'self_contained') THEN 1 ELSE 0 END), 0) AS desirable
           FROM claim_extraction_evaluations
           WHERE decontextualization_result IS NOT NULL"""
    )
    decontextualization = dict(await cursor.fetchone())
    result["desirable_decontextualization_rate"] = (
        decontextualization["desirable"] / decontextualization["total"]
        if decontextualization["total"] else None
    )
    cursor = await db.execute(
        "SELECT verdict, COUNT(*) AS count FROM claim_verification_runs GROUP BY verdict"
    )
    result["verdicts"] = {row["verdict"]: row["count"] for row in await cursor.fetchall()}
    cursor = await db.execute(
        "SELECT category, COUNT(*) AS count FROM claim_explanation_runs GROUP BY category"
    )
    result["improvement_routes"] = {
        row["category"]: row["count"] for row in await cursor.fetchall()
    }
    improvement_total = sum(result["improvement_routes"].values())
    result["improvement_route_rates"] = {
        category: count / improvement_total
        for category, count in result["improvement_routes"].items()
    } if improvement_total else {}
    cursor = await db.execute(
        """SELECT COUNT(*) AS compared,
                  COALESCE(SUM(CASE WHEN verdict_count = 1 THEN 1 ELSE 0 END), 0) AS agreed
           FROM (
             SELECT claim_occurrence_id, COUNT(DISTINCT verdict) AS verdict_count
             FROM claim_verification_runs GROUP BY claim_occurrence_id HAVING COUNT(*) > 1
           )"""
    )
    agreement = dict(await cursor.fetchone())
    result["cross_verifier_agreement"] = (
        agreement["agreed"] / agreement["compared"] if agreement["compared"] else None
    )
    cursor = await db.execute("SELECT COUNT(*) AS count FROM claim_human_overrides")
    result["human_override_count"] = (await cursor.fetchone())["count"]
    result["human_override_rate"] = (
        result["human_override_count"] / result["occurrences"]
        if result["occurrences"] else None
    )
    cursor = await db.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN human_review_required = 1 THEN 1 ELSE 0 END), 0)
                    AS human_review_required
           FROM claim_explanation_runs"""
    )
    review = dict(await cursor.fetchone())
    result["human_review_rate"] = (
        review["human_review_required"] / review["total"] if review["total"] else None
    )
    cursor = await db.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END), 0) AS passed
           FROM claim_regression_runs crr
           WHERE crr.id IN (
             SELECT MAX(id) FROM claim_regression_runs
             GROUP BY explanation_run_id, dataset_fqn, implementation_revision
           )"""
    )
    regression = dict(await cursor.fetchone())
    result["regression_pass_rate"] = (
        regression["passed"] / regression["total"] if regression["total"] else None
    )
    cursor = await db.execute(
        """SELECT COUNT(*) AS events,
                  COALESCE(SUM(CASE WHEN agent_job_avoided = 1 THEN 1 ELSE 0 END), 0)
                    AS agent_jobs_avoided
           FROM claim_stage_receipt_events"""
    )
    result["receipts"] = dict(await cursor.fetchone())
    denominator = result["occurrences"] or 1
    result["source_entailment_rate"] = result["entailed_occurrences"] / denominator
    result["unresolved_ambiguity_rate"] = (
        result["unresolved_units"] / result["source_units"]
        if result["source_units"] else None
    )
    result["breakdowns"] = await _get_assurance_breakdowns(db)
    return result


async def list_extraction_runs(
    db: aiosqlite.Connection, limit: int, offset: int
) -> dict:
    cursor = await db.execute("SELECT COUNT(*) AS count FROM claim_extraction_runs")
    total = (await cursor.fetchone())["count"]
    cursor = await db.execute(
        """SELECT cer.*,
                  COUNT(DISTINCT csu.id) AS source_unit_count,
                  COUNT(DISTINCT co.id) AS occurrence_count,
                  COUNT(DISTINCT CASE WHEN car.status = 'unresolved' THEN csu.id END)
                    AS unresolved_count,
                  COUNT(DISTINCT CASE WHEN cee.entailed = 0 THEN co.id END)
                    AS entailment_failure_count
           FROM claim_extraction_runs cer
           LEFT JOIN claim_source_units csu ON csu.extraction_run_id = cer.id
           LEFT JOIN claim_ambiguity_results car ON car.source_unit_id = csu.id
           LEFT JOIN claim_occurrences co ON co.source_unit_id = csu.id
           LEFT JOIN claim_extraction_evaluations cee ON cee.claim_occurrence_id = co.id
           GROUP BY cer.id ORDER BY cer.started_at DESC, cer.id DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    return {"runs": [dict(row) for row in await cursor.fetchall()], "total": total}


async def get_extraction_run(db: aiosqlite.Connection, run_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM claim_extraction_runs WHERE id = ?", (run_id,))
    run = await cursor.fetchone()
    if not run:
        return None
    cursor = await db.execute(
        """SELECT csu.*, csr.classification, csr.selected_text,
                  csr.rationale AS selection_rationale, car.status AS ambiguity_status,
                  car.ambiguity_types, car.clarified_text, car.resolution_context,
                  car.rationale AS ambiguity_rationale
           FROM claim_source_units csu
           LEFT JOIN claim_selection_results csr ON csr.source_unit_id = csu.id
           LEFT JOIN claim_ambiguity_results car ON car.source_unit_id = csu.id
           WHERE csu.extraction_run_id = ? ORDER BY csu.id""",
        (run_id,),
    )
    units = [dict(row) for row in await cursor.fetchall()]
    for unit in units:
        claim_cursor = await db.execute(
            """SELECT co.*, cee.entailed, cee.entailment_rationale,
                      cee.coverage_result, cee.decontextualization_result,
                      cee.maximally_contextualized_claim,
                      cee.extracted_retrieval_digest,
                      cee.comparison_retrieval_digest,
                      cee.evaluator_revision
               FROM claim_occurrences co
               LEFT JOIN claim_extraction_evaluations cee
                 ON cee.claim_occurrence_id = co.id
               WHERE co.source_unit_id = ? ORDER BY co.id""",
            (unit["id"],),
        )
        unit["occurrences"] = [dict(row) for row in await claim_cursor.fetchall()]
        for occurrence in unit["occurrences"]:
            coverage_cursor = await db.execute(
                """SELECT cce.* FROM claim_coverage_elements cce
                   JOIN claim_extraction_evaluations cee
                     ON cee.id = cce.extraction_evaluation_id
                   WHERE cee.claim_occurrence_id = ? ORDER BY cce.id""",
                (occurrence["id"],),
            )
            occurrence["coverage_elements"] = [
                dict(row) for row in await coverage_cursor.fetchall()
            ]
            evaluation_cursor = await db.execute(
                """SELECT id FROM claim_extraction_evaluations
                   WHERE claim_occurrence_id = ? ORDER BY id DESC LIMIT 1""",
                (occurrence["id"],),
            )
            evaluation = await evaluation_cursor.fetchone()
            occurrence["extraction_evidence"] = []
            if evaluation:
                evidence_cursor = await db.execute(
                    """SELECT * FROM claim_evidence_records
                       WHERE stage = 'extraction' AND stage_run_id = ? ORDER BY id""",
                    (evaluation["id"],),
                )
                occurrence["extraction_evidence"] = [
                    dict(row) for row in await evidence_cursor.fetchall()
                ]
    return {"run": dict(run), "source_units": units}


async def list_occurrences_for_verification(
    db: aiosqlite.Connection, jira_key: str | None, pending_only: bool, limit: int
) -> list[dict]:
    where = ["cee.entailed = 1", "co.accepted = 1"]
    params: list[object] = []
    if jira_key:
        where.append(
            "EXISTS (SELECT 1 FROM claim_occurrence_jira_keys cojk "
            "WHERE cojk.claim_occurrence_id = co.id AND cojk.jira_key = ?)"
        )
        params.append(jira_key.upper())
    if pending_only:
        where.append(
            "NOT EXISTS (SELECT 1 FROM claim_verification_runs cvr WHERE cvr.claim_occurrence_id = co.id)"
        )
    params.append(limit)
    cursor = await db.execute(
        f"""SELECT co.*, c.claim_hash, csu.source_locator, csu.original_text AS source_unit_text,
                   csu.preceding_context, csu.following_context,
                   cee.entailed AS extraction_entailed, cee.coverage_result,
                   cee.decontextualization_result, cer.source_file, cer.pipeline_slug
            FROM claim_occurrences co
            JOIN claims c ON c.id = co.normalized_claim_id
            JOIN claim_source_units csu ON csu.id = co.source_unit_id
            JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
            JOIN claim_extraction_evaluations cee ON cee.claim_occurrence_id = co.id
            WHERE {' AND '.join(where)} ORDER BY co.id LIMIT ?""",  # noqa: S608
        params,
    )
    return [dict(row) for row in await cursor.fetchall()]


async def create_human_override(db: aiosqlite.Connection, data: HumanOverrideInput) -> dict:
    cursor = await db.execute(
        """INSERT INTO claim_human_overrides
           (claim_occurrence_id, verification_run_id, actor, decision, rationale)
           VALUES (?, ?, ?, ?, ?)""",
        (data.claim_occurrence_id, data.verification_run_id, data.actor,
         data.decision, data.rationale),
    )
    await db.commit()
    return {"id": cursor.lastrowid}


async def create_regression_run(db: aiosqlite.Connection, data: RegressionRunInput) -> dict:
    cursor = await db.execute(
        """INSERT INTO claim_regression_runs
           (explanation_run_id, dataset_fqn, implementation_revision, status,
            metrics, run_uri) VALUES (?, ?, ?, ?, ?, ?)""",
        (data.explanation_run_id, data.dataset_fqn, data.implementation_revision,
         data.status, json.dumps(data.metrics, sort_keys=True), data.run_uri),
    )
    await db.commit()
    return {"id": cursor.lastrowid}


async def create_receipt_event(db: aiosqlite.Connection, data: StageReceiptEventInput) -> dict:
    cursor = await db.execute(
        """INSERT INTO claim_stage_receipt_events
           (stage, scope_key, input_digest, evidence_context_digest, skill_fqn,
            skill_revision, model, harness, configuration_digest, status,
            agent_job_avoided, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.stage, data.scope_key, data.input_digest, data.evidence_context_digest,
         data.skill_fqn, data.skill_revision, data.model, data.harness,
         data.configuration_digest, data.status, data.agent_job_avoided,
         json.dumps(data.details, sort_keys=True)),
    )
    await db.commit()
    return {"id": cursor.lastrowid}
