from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from typing import Any

import aiosqlite

from backend.crud.claim_triage import TRIAGE_CTES


SCHEMA_VERSION = "claim-assurance-report.v1"
DEFAULT_EXPORT_LIMIT = 1000
REPORT_JOB_RETENTION_DAYS = 30


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _processing_state(history: dict[str, Any]) -> str:
    effective_verification_id = history.get("effective_verification_run_id")
    if effective_verification_id is None:
        return "not_verified"
    effective_verification = next(
        run for run in history["verification_runs"]
        if run["id"] == effective_verification_id
    )
    effective_explanations = effective_verification.get("explanation_runs", [])
    if not effective_explanations:
        return "verified_without_explanation"
    effective_explanation_id = history.get("effective_explanation_run_id")
    effective_explanation = next(
        run for run in effective_explanations if run["id"] == effective_explanation_id
    )
    if effective_explanation.get("human_review_required") == 1:
        return "explanation_requires_human_review"
    return "explained"


def _filter_values(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in filters.items()
        if value not in (None, "", [])
    }


def _where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    where = ["co.accepted = 1"]
    params: list[Any] = []
    if filters.get("claim_occurrence_id") is not None:
        where.append("co.id = ?")
        params.append(filters["claim_occurrence_id"])
    if filters.get("normalized_claim_id") is not None:
        where.append("co.normalized_claim_id = ?")
        params.append(filters["normalized_claim_id"])
    if filters.get("canonical_group_id") is not None:
        where.append("membership.canonical_group_id = ?")
        params.append(filters["canonical_group_id"])
    if filters.get("artifact_type"):
        where.append("cer.artifact_type = ?")
        params.append(filters["artifact_type"])
    if filters.get("pipeline_slug"):
        where.append("cer.pipeline_slug = ?")
        params.append(filters["pipeline_slug"])
    if filters.get("source_file"):
        where.append("cer.source_file LIKE ?")
        params.append(f"%{filters['source_file']}%")
    if filters.get("claim_type"):
        where.append("co.claim_type = ?")
        params.append(filters["claim_type"])
    verdict = filters.get("verdict")
    if verdict:
        if verdict == "pending":
            where.append("lv.id IS NULL")
        else:
            where.append("lv.verdict = ?")
            params.append(verdict)
    if filters.get("processing_state"):
        state = filters["processing_state"]
        if state == "not_verified":
            where.append("lv.id IS NULL")
        elif state == "verified_without_explanation":
            where.append("lv.id IS NOT NULL AND le.id IS NULL")
        elif state == "explanation_requires_human_review":
            where.append("le.human_review_required = 1")
        elif state == "explained":
            where.append("le.id IS NOT NULL AND le.human_review_required = 0")
    if filters.get("explanation_category"):
        where.append("le.category = ?")
        params.append(filters["explanation_category"])
    if filters.get("improvement_target"):
        where.append("le.improvement_target = ?")
        params.append(filters["improvement_target"])
    if filters.get("human_review_required") is not None:
        where.append("le.human_review_required = ?")
        params.append(filters["human_review_required"])
    if filters.get("jira_key"):
        where.append(
            "EXISTS (SELECT 1 FROM claim_occurrence_jira_keys cojk "
            "WHERE cojk.claim_occurrence_id = co.id AND cojk.jira_key = ?)"
        )
        params.append(filters["jira_key"].upper())
    if filters.get("created_after"):
        where.append("co.created_at >= ?")
        params.append(filters["created_after"])
    if filters.get("created_before"):
        where.append("co.created_at <= ?")
        params.append(filters["created_before"])
    return " AND ".join(where), params


async def _evidence(db: aiosqlite.Connection, stage: str, run_id: int) -> list[dict]:
    cursor = await db.execute(
        """SELECT id, evidence_type, uri, repository_revision, artifact_digest,
                  source_locator, query, excerpt, relationship, authority,
                  product_version, retrieved_at, created_at
           FROM claim_evidence_records
           WHERE stage = ? AND stage_run_id = ? ORDER BY id""",
        (stage, run_id),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def _occurrence_jira_keys(db: aiosqlite.Connection, occurrence_id: int) -> list[str]:
    cursor = await db.execute(
        """SELECT jira_key FROM claim_occurrence_jira_keys
           WHERE claim_occurrence_id = ? ORDER BY jira_key""",
        (occurrence_id,),
    )
    return [row["jira_key"] for row in await cursor.fetchall()]


async def _extraction_evaluation(
    db: aiosqlite.Connection, occurrence_id: int
) -> dict[str, Any] | None:
    cursor = await db.execute(
        """SELECT * FROM claim_extraction_evaluations
           WHERE claim_occurrence_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
        (occurrence_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    result = dict(row)
    coverage = await db.execute(
        """SELECT id, element_text, element_kind, coverage, rationale
           FROM claim_coverage_elements
           WHERE extraction_evaluation_id = ? ORDER BY id""",
        (result["id"],),
    )
    result["coverage_elements"] = [dict(item) for item in await coverage.fetchall()]
    result["evidence"] = await _evidence(db, "extraction", result["id"])
    return result


async def _verification_runs(
    db: aiosqlite.Connection, occurrence_id: int
) -> list[dict[str, Any]]:
    cursor = await db.execute(
        """SELECT id, claim_occurrence_id, verifier_revision, repository_revision,
                  model, harness, configuration_digest, evidence_context_digest,
                  verdict, severity, confidence, evidence_summary, token_count,
                  cost_usd, duration_seconds, created_at
           FROM claim_verification_runs
           WHERE claim_occurrence_id = ? ORDER BY created_at, id""",
        (occurrence_id,),
    )
    runs = [dict(row) for row in await cursor.fetchall()]
    for run in runs:
        run["evidence"] = await _evidence(db, "verification", run["id"])
        explanation_cursor = await db.execute(
            """SELECT id, verification_run_id, explainer_revision,
                      repository_revision, model, harness, configuration_digest,
                      category, improvement_target, explanation,
                      contributing_factors, alternative_explanations, remediation,
                      regression_test, human_review_required, token_count, cost_usd,
                      duration_seconds, created_at
               FROM claim_explanation_runs
               WHERE verification_run_id = ? ORDER BY created_at, id""",
            (run["id"],),
        )
        explanations = [dict(row) for row in await explanation_cursor.fetchall()]
        for explanation in explanations:
            explanation["contributing_factors"] = _loads(
                explanation.get("contributing_factors"), []
            )
            explanation["alternative_explanations"] = _loads(
                explanation.get("alternative_explanations"), []
            )
            explanation["evidence"] = await _evidence(db, "explanation", explanation["id"])
            regression_cursor = await db.execute(
                """SELECT id, explanation_run_id, dataset_fqn,
                          implementation_revision, status, metrics, run_uri,
                          created_at
                   FROM claim_regression_runs
                   WHERE explanation_run_id = ? ORDER BY id""",
                (explanation["id"],),
            )
            explanation["regression_runs"] = [
                {**dict(row), "metrics": _loads(dict(row).get("metrics"), {})}
                for row in await regression_cursor.fetchall()
            ]
        run["explanation_runs"] = explanations
    return runs


async def _human_overrides(db: aiosqlite.Connection, occurrence_id: int) -> list[dict]:
    cursor = await db.execute(
        """SELECT id, claim_occurrence_id, verification_run_id, actor, decision,
                  rationale, created_at
           FROM claim_human_overrides
           WHERE claim_occurrence_id = ? ORDER BY id""",
        (occurrence_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def _occurrence(db: aiosqlite.Connection, occurrence_id: int) -> dict[str, Any]:
    cursor = await db.execute(
        """SELECT co.id, co.normalized_claim_id, co.claim_text, co.original_text,
                  co.claim_type, co.modality, co.product_version,
                  co.temporal_scope, co.clarification, co.accepted,
                  co.created_at, c.claim_hash, csu.id AS source_unit_id,
                  csu.unit_key, csu.unit_kind, csu.source_locator,
                  csu.original_text AS source_unit_text, csu.heading_path,
                  csu.preceding_context, csu.following_context, csu.list_preamble,
                  cer.id AS extraction_run_id, cer.run_key AS extraction_run_key,
                  cer.source_file, cer.pipeline_slug, cer.artifact_type,
                  cer.artifact_digest, cer.extractor_revision,
                  cer.repository_revision AS extraction_repository_revision,
                  cer.model AS extraction_model, cer.harness AS extraction_harness,
                  cer.configuration_digest AS extraction_configuration_digest,
                  cer.token_count AS extraction_token_count,
                  cer.cost_usd AS extraction_cost_usd,
                  cer.duration_seconds AS extraction_duration_seconds,
                  membership.canonical_group_id, canonical.canonical_text
           FROM claim_occurrences co
           JOIN claims c ON c.id = co.normalized_claim_id
           JOIN claim_source_units csu ON csu.id = co.source_unit_id
           JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
           LEFT JOIN claim_canonical_memberships membership
             ON membership.normalized_claim_id = co.normalized_claim_id
            AND membership.retired_at IS NULL
           LEFT JOIN claim_canonical_groups canonical
             ON canonical.id = membership.canonical_group_id
            AND canonical.retired_at IS NULL
           WHERE co.id = ?""",
        (occurrence_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise LookupError(f"claim occurrence {occurrence_id} not found")
    base = dict(row)
    verification_runs = await _verification_runs(db, occurrence_id)
    effective_verification = verification_runs[-1] if verification_runs else None
    effective_explanation = (
        effective_verification["explanation_runs"][-1]
        if effective_verification and effective_verification["explanation_runs"] else None
    )
    history = {
        "id": base["id"],
        "normalized_claim_id": base["normalized_claim_id"],
        "claim_hash": base["claim_hash"],
        "canonical_group": _compact({
            "id": base.get("canonical_group_id"),
            "canonical_text": base.get("canonical_text"),
        }) or None,
        "claim_text": base["claim_text"],
        "original_text": base.get("original_text"),
        "claim_type": base.get("claim_type"),
        "modality": base.get("modality"),
        "product_version": base.get("product_version"),
        "temporal_scope": base.get("temporal_scope"),
        "clarification": base.get("clarification"),
        "accepted": base["accepted"],
        "created_at": base.get("created_at"),
        "jira_keys": await _occurrence_jira_keys(db, occurrence_id),
        "source": {
            "file": base["source_file"],
            "locator": base["source_locator"],
            "pipeline_slug": base["pipeline_slug"],
            "artifact_type": base["artifact_type"],
            "artifact_digest": base.get("artifact_digest"),
            "source_unit_id": base["source_unit_id"],
            "unit_key": base["unit_key"],
            "unit_kind": base["unit_kind"],
            "source_unit_text": base.get("source_unit_text"),
            "heading_path": _loads(base.get("heading_path"), []),
            "preceding_context": _loads(base.get("preceding_context"), []),
            "following_context": _loads(base.get("following_context"), []),
            "list_preamble": base.get("list_preamble"),
        },
        "extraction_run": {
            "id": base["extraction_run_id"],
            "run_key": base["extraction_run_key"],
            "extractor_revision": base["extractor_revision"],
            "repository_revision": base.get("extraction_repository_revision"),
            "model": base.get("extraction_model"),
            "harness": base.get("extraction_harness"),
            "configuration_digest": base.get("extraction_configuration_digest"),
            "token_count": base.get("extraction_token_count"),
            "cost_usd": base.get("extraction_cost_usd"),
            "duration_seconds": base.get("extraction_duration_seconds"),
        },
        "extraction_evaluation": await _extraction_evaluation(db, occurrence_id),
        "effective_verification_run_id": (
            effective_verification["id"] if effective_verification else None
        ),
        "effective_explanation_run_id": (
            effective_explanation["id"] if effective_explanation else None
        ),
        "verification_runs": verification_runs,
        "human_overrides": await _human_overrides(db, occurrence_id),
    }
    history["processing_state"] = _processing_state(history)
    return history


def _counter(items: list[str | int | None]) -> list[dict[str, Any]]:
    counts = Counter(item if item is not None else "unknown" for item in items)
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def _aggregates(occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    effective_verdicts = []
    explanation_categories = []
    improvement_targets = []
    canonical_groups = []
    jira_keys = []
    human_review_required = 0
    for occurrence in occurrences:
        effective = None
        for run in occurrence["verification_runs"]:
            if run["id"] == occurrence.get("effective_verification_run_id"):
                effective = run
                break
        effective_verdicts.append(effective["verdict"] if effective else "pending")
        if occurrence.get("canonical_group"):
            canonical_groups.append(occurrence["canonical_group"]["id"])
        jira_keys.extend(occurrence["jira_keys"])
        if occurrence["processing_state"] == "explanation_requires_human_review":
            human_review_required += 1
        if effective:
            for explanation in effective.get("explanation_runs", []):
                explanation_categories.append(explanation.get("category"))
                improvement_targets.append(explanation.get("improvement_target"))
    return {
        "by_verdict": _counter(effective_verdicts),
        "by_claim_type": _counter([item.get("claim_type") for item in occurrences]),
        "by_artifact_type": _counter([
            item["source"].get("artifact_type") for item in occurrences
        ]),
        "by_source_file": _counter([item["source"].get("file") for item in occurrences]),
        "by_jira_key": _counter(jira_keys),
        "by_explanation_category": _counter(explanation_categories),
        "by_improvement_target": _counter(improvement_targets),
        "by_canonical_group": _counter(canonical_groups),
        "human_review_required": human_review_required,
        "repeated_normalized_claims": [
            {"normalized_claim_id": claim_id, "occurrence_count": count}
            for claim_id, count in Counter(
                item["normalized_claim_id"] for item in occurrences
            ).items() if count > 1
        ],
    }


async def _canonical_groups(
    db: aiosqlite.Connection, occurrences: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    group_ids = sorted({
        item["canonical_group"]["id"] for item in occurrences
        if item.get("canonical_group")
    })
    if not group_ids:
        return []
    placeholders = ",".join("?" for _ in group_ids)
    cursor = await db.execute(
        f"""SELECT id, canonical_text, subject_key, qualifier_summary,
                  policy_revision, created_at, retired_at
           FROM claim_canonical_groups WHERE id IN ({placeholders})
           ORDER BY id""",  # noqa: S608
        group_ids,
    )
    groups = [dict(row) for row in await cursor.fetchall()]
    for group in groups:
        group["qualifier_summary"] = _loads(group.get("qualifier_summary"), {})
        member_cursor = await db.execute(
            """SELECT id, canonical_group_id, normalized_claim_id, decision_id,
                      actor, created_at, retired_at
               FROM claim_canonical_memberships
               WHERE canonical_group_id = ? ORDER BY retired_at IS NOT NULL, id""",
            (group["id"],),
        )
        group["memberships"] = [dict(row) for row in await member_cursor.fetchall()]
        decision_ids = [
            row["decision_id"] for row in group["memberships"] if row.get("decision_id")
        ]
        if decision_ids:
            decision_placeholders = ",".join("?" for _ in decision_ids)
            decision_cursor = await db.execute(
                f"""SELECT id, candidate_id, decision, rationale,
                          compared_qualifiers, decider_type, decider_revision,
                          actor, confidence, created_at, supersedes_decision_id
                   FROM claim_equivalence_decisions
                   WHERE id IN ({decision_placeholders}) ORDER BY id""",  # noqa: S608
                decision_ids,
            )
            group["equivalence_decisions"] = [
                {**dict(row), "compared_qualifiers": _loads(row["compared_qualifiers"], {})}
                for row in await decision_cursor.fetchall()
            ]
        else:
            group["equivalence_decisions"] = []
    return groups


async def build_claim_assurance_report(
    db: aiosqlite.Connection,
    filters: dict[str, Any],
    *,
    observatory_url: str | None = None,
    limit: int = DEFAULT_EXPORT_LIMIT,
) -> dict[str, Any]:
    active_filters = _filter_values(filters)
    where_sql, params = _where_clause(active_filters)
    base_from = """FROM claim_occurrences co
        JOIN claim_source_units csu ON csu.id = co.source_unit_id
        JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
        LEFT JOIN claim_canonical_memberships membership
          ON membership.normalized_claim_id = co.normalized_claim_id
         AND membership.retired_at IS NULL
        LEFT JOIN latest_verification lv ON lv.claim_occurrence_id = co.id
        LEFT JOIN latest_explanation le ON le.verification_run_id = lv.id"""
    cursor = await db.execute(
        TRIAGE_CTES + f"SELECT COUNT(*) AS count {base_from} WHERE {where_sql}",  # noqa: S608
        params,
    )
    total = (await cursor.fetchone())["count"]
    warnings = []
    if total > limit:
        warnings.append(
            f"export limited to {limit} of {total} matching claim occurrences"
        )
    cursor = await db.execute(
        TRIAGE_CTES + f"""SELECT co.id {base_from} WHERE {where_sql}
           ORDER BY co.id LIMIT ?""",  # noqa: S608
        [*params, limit],
    )
    occurrence_ids = [row["id"] for row in await cursor.fetchall()]
    occurrences = [await _occurrence(db, occurrence_id) for occurrence_id in occurrence_ids]
    aggregate_data = _aggregates(occurrences)
    verdict_counts = {
        item["value"]: item["count"] for item in aggregate_data["by_verdict"]
    }
    summary = {
        "matching_occurrences": total,
        "exported_occurrences": len(occurrences),
        "verification_runs": sum(len(item["verification_runs"]) for item in occurrences),
        "explanation_runs": sum(
            len(run["explanation_runs"])
            for item in occurrences for run in item["verification_runs"]
        ),
        "human_overrides": sum(len(item["human_overrides"]) for item in occurrences),
        "canonical_groups": len({
            item["canonical_group"]["id"] for item in occurrences
            if item.get("canonical_group")
        }),
        "pending": verdict_counts.get("pending", 0),
        "supported": verdict_counts.get("supported", 0),
        "contradicted": verdict_counts.get("contradicted", 0),
        "insufficient_evidence": verdict_counts.get("insufficient_evidence", 0),
        "not_applicable": verdict_counts.get("not_applicable", 0),
        "human_review_required": aggregate_data["human_review_required"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "observatory_url": observatory_url,
        "filters": active_filters,
        "summary": summary,
        "occurrences": occurrences,
        "canonical_groups": await _canonical_groups(db, occurrences),
        "aggregates": aggregate_data,
        "warnings": warnings,
    }


def _line(value: Any) -> str:
    return str(value).replace("\n", " ").strip()


def render_claim_assurance_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Claim Assurance Report",
        "",
        f"- Schema version: `{report['schema_version']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Observatory URL: `{report.get('observatory_url') or 'unknown'}`",
        f"- Filters: `{json.dumps(report['filters'], sort_keys=True)}`",
        "",
        "## Summary",
        "",
        f"- Matching occurrences: {summary['matching_occurrences']}",
        f"- Exported occurrences: {summary['exported_occurrences']}",
        f"- Verification runs: {summary['verification_runs']}",
        f"- Explanation runs: {summary['explanation_runs']}",
        f"- Canonical groups: {summary['canonical_groups']}",
        f"- Contradicted: {summary['contradicted']}",
        f"- Insufficient evidence: {summary['insufficient_evidence']}",
        f"- Human review required: {summary['human_review_required']}",
    ]
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.extend(["", "## Hotspots", ""])
    for title, key in (
        ("Verdicts", "by_verdict"),
        ("Jira keys", "by_jira_key"),
        ("Source files", "by_source_file"),
        ("Improvement targets", "by_improvement_target"),
        ("Canonical groups", "by_canonical_group"),
    ):
        lines.extend([f"### {title}", ""])
        values = report["aggregates"].get(key, [])
        lines.extend(
            [f"- `{item['value']}`: {item['count']}" for item in values]
            if values else ["- None"]
        )
        lines.append("")
    lines.extend(["## Occurrences", ""])
    for occurrence in report["occurrences"]:
        effective = next(
            (
                run for run in occurrence["verification_runs"]
                if run["id"] == occurrence.get("effective_verification_run_id")
            ),
            None,
        )
        effective_explanation = None
        if effective:
            effective_explanation = next(
                (
                    run for run in effective.get("explanation_runs", [])
                    if run["id"] == occurrence.get("effective_explanation_run_id")
                ),
                None,
            )
        lines.extend([
            f"### Occurrence {occurrence['id']}",
            "",
            f"> {_line(occurrence['claim_text'])}",
            "",
            f"- Normalized claim ID: {occurrence['normalized_claim_id']}",
            f"- Claim type: `{occurrence.get('claim_type') or 'unknown'}`",
            f"- Processing state: `{occurrence['processing_state']}`",
            f"- Source: `{occurrence['source']['file']}` · `{occurrence['source']['locator']}`",
            f"- Jira keys: {', '.join(occurrence['jira_keys']) or 'none'}",
            f"- Effective verdict: `{effective['verdict'] if effective else 'pending'}`",
        ])
        if occurrence.get("canonical_group"):
            group = occurrence["canonical_group"]
            lines.append(f"- Canonical group: #{group['id']} — {_line(group['canonical_text'])}")
        if effective and effective.get("evidence_summary"):
            lines.append(f"- Evidence summary: {_line(effective['evidence_summary'])}")
        if effective_explanation:
            lines.extend([
                f"- Explanation category: `{effective_explanation['category']}`",
                f"- Improvement target: `{effective_explanation.get('improvement_target') or 'unknown'}`",
                f"- Remediation: {_line(effective_explanation.get('remediation') or 'none')}",
                "",
                _line(effective_explanation["explanation"]),
            ])
        lines.append("")
    lines.extend(["## Appendix: Verification History", ""])
    for occurrence in report["occurrences"]:
        lines.extend([f"### Occurrence {occurrence['id']} history", ""])
        if not occurrence["verification_runs"]:
            lines.extend(["- No verification runs.", ""])
            continue
        for run in occurrence["verification_runs"]:
            lines.extend([
                f"- Verification run #{run['id']}: `{run['verdict']}` "
                f"confidence {run.get('confidence') if run.get('confidence') is not None else 'unknown'}",
                f"  - Verifier revision: `{run['verifier_revision']}`",
                f"  - Evidence records: {len(run['evidence'])}",
                f"  - Explanation runs: {len(run['explanation_runs'])}",
            ])
    return "\n".join(lines).rstrip() + "\n"


async def create_claim_report_job(
    db: aiosqlite.Connection,
    *,
    report_format: str,
    filters: dict[str, Any],
    observatory_url: str | None,
    limit: int,
) -> dict[str, Any]:
    cursor = await db.execute(
        """INSERT INTO claim_report_jobs
           (status, report_format, filters, limit_count, observatory_url, started_at)
           VALUES ('running', ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (report_format, json.dumps(_filter_values(filters), sort_keys=True), limit, observatory_url),
    )
    job_id = cursor.lastrowid
    try:
        report = await build_claim_assurance_report(
            db, filters, observatory_url=observatory_url, limit=limit
        )
        json_report = json.dumps(report, indent=2, sort_keys=True) if report_format in {"json", "both"} else None
        markdown_report = render_claim_assurance_markdown(report) if report_format in {"markdown", "both"} else None
        expires_at = datetime.now(UTC) + timedelta(days=REPORT_JOB_RETENTION_DAYS)
        await db.execute(
            """UPDATE claim_report_jobs
               SET status = 'complete', summary = ?, json_report = ?,
                   markdown_report = ?, completed_at = CURRENT_TIMESTAMP,
                   expires_at = ?
               WHERE id = ?""",
            (
                json.dumps(report["summary"], sort_keys=True), json_report,
                markdown_report, expires_at.replace(microsecond=0).isoformat(), job_id,
            ),
        )
        await db.commit()
    except Exception as exc:
        await db.execute(
            """UPDATE claim_report_jobs
               SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (str(exc), job_id),
        )
        await db.commit()
        raise
    result = await get_claim_report_job(db, job_id)
    if result is None:
        raise LookupError(f"claim report job {job_id} was not persisted")
    return result


async def get_claim_report_job(
    db: aiosqlite.Connection, report_id: int
) -> dict[str, Any] | None:
    cursor = await db.execute(
        """SELECT id, status, report_format, filters, limit_count,
                  observatory_url, summary, error, created_at, started_at,
                  completed_at, expires_at,
                  json_report IS NOT NULL AS has_json,
                  markdown_report IS NOT NULL AS has_markdown
           FROM claim_report_jobs WHERE id = ?""",
        (report_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    result = dict(row)
    result["filters"] = _loads(result.get("filters"), {})
    result["summary"] = _loads(result.get("summary"), {})
    result["has_json"] = bool(result["has_json"])
    result["has_markdown"] = bool(result["has_markdown"])
    return result


async def get_claim_report_artifact(
    db: aiosqlite.Connection, report_id: int, report_format: str
) -> tuple[str, str] | None:
    column = "json_report" if report_format == "json" else "markdown_report"
    cursor = await db.execute(
        f"SELECT status, {column} AS content FROM claim_report_jobs WHERE id = ?",  # noqa: S608
        (report_id,),
    )
    row = await cursor.fetchone()
    if not row or row["status"] != "complete" or row["content"] is None:
        return None
    media_type = "application/json" if report_format == "json" else "text/markdown"
    return row["content"], media_type
