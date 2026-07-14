from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import base64
import aiosqlite
import httpx

from backend.crud import data_sources as ds_crud
from backend.crud import claim_assurance as claim_assurance_crud
from backend.crud import claim_triage as claim_triage_crud
from backend.crud import kb as kb_crud
from backend.crud import pipelines as pipelines_crud
from backend.crud import runs as runs_crud

log = logging.getLogger(__name__)


TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "query_pipelines",
        "description": "List CI/CD pipelines tracked by Observatory. Filter by status, group, or platform.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by pipeline status (e.g. production, disabled)"},
                "group": {"type": "string", "description": "Filter by pipeline group"},
                "platform": {"type": "string", "description": "Filter by platform (gitlab, github)"},
                "limit": {"type": "integer", "description": "Max results to return", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "query_runs",
        "description": "Get recent pipeline runs. Filter by pipeline, status, or date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_slug": {"type": "string", "description": "Pipeline slug to filter runs for"},
                "status": {"type": "string", "description": "Filter by run status (success, failed, running)"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
            "required": [],
        },
    },
    {
        "name": "query_claims",
        "description": (
            "Search claim occurrences from the Claim Assurance v2 system. "
            "Each result is a specific occurrence (not a deduplicated claim). "
            "Filter by occurrence ID, text search, claim type, verdict, pipeline, "
            "Jira key, or source file. "
            "Canonical verdicts: supported, contradicted, insufficient_evidence, "
            "not_applicable. Use verdict 'pending' for unverified occurrences. "
            "Use get_claim_occurrence_history for full verification and explanation history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_id": {"type": "integer", "description": "Exact occurrence ID lookup"},
                "search": {"type": "string", "description": "Text search in claim content"},
                "claim_type": {"type": "string", "description": "Filter by claim type"},
                "verdict": {
                    "type": "string",
                    "enum": ["supported", "contradicted", "insufficient_evidence", "not_applicable", "pending"],
                    "description": "Filter by effective verdict",
                },
                "pipeline_slug": {"type": "string", "description": "Filter claims from a specific pipeline"},
                "source": {"type": "string", "description": "Filter by source file path pattern"},
                "jira_key": {"type": "string", "description": "Filter claims linked to a specific Jira issue (e.g. RHAISTRAT-320)"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
            },
            "required": [],
        },
    },
    {
        "name": "get_claim_occurrence_history",
        "description": (
            "Get the full immutable history of a specific claim occurrence: "
            "all verification runs with evidence, explanation runs with category/"
            "improvement target/remediation/regression status, and human overrides. "
            "Shows effective (newest) verification and explanation IDs. "
            "Use this when asked about evidence, why a verdict changed, or details "
            "of a specific occurrence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_id": {"type": "integer", "description": "The claim occurrence ID"},
            },
            "required": ["occurrence_id"],
        },
    },
    {
        "name": "query_claim_explanations",
        "description": (
            "Search immutable v2 explanation runs. Filter by root-cause category, "
            "improvement target, Jira key, or human-review requirement. "
            "Returns structured explanation data including contributing factors, "
            "alternatives, remediation, and regression status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by explanation category"},
                "improvement_target": {"type": "string", "description": "Filter by improvement target"},
                "jira_key": {"type": "string", "description": "Filter by linked Jira key"},
                "human_review_required": {"type": "boolean", "description": "Filter by human review requirement"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
            },
            "required": [],
        },
    },
    {
        "name": "get_claim_assurance_summary",
        "description": (
            "Get the effective occurrence-level summary from Claim Assurance v2: "
            "total occurrences, verdict distribution (supported/contradicted/"
            "insufficient_evidence/not_applicable/pending), explanation and "
            "human-review counts. These are effective counts per occurrence, "
            "not total immutable run counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "query_telemetry",
        "description": "Get token usage and cost telemetry data. Returns per-model and per-skill breakdowns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_slug": {"type": "string", "description": "Filter to a specific pipeline"},
            },
            "required": [],
        },
    },
    {
        "name": "query_vulnerabilities",
        "description": "Search known vulnerabilities (CVEs) found in container SBOMs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "description": "Filter by severity (critical, high, medium, low)"},
                "package_name": {"type": "string", "description": "Filter by package name"},
                "limit": {"type": "integer", "description": "Max results", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "query_artifacts",
        "description": "List job artifacts collected from pipeline runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_slug": {"type": "string", "description": "Filter by pipeline slug"},
                "file_path": {"type": "string", "description": "Filter by file path pattern"},
                "limit": {"type": "integer", "description": "Max results", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "kb_search",
        "description": "Full-text search across knowledge base articles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_get",
        "description": "Get a specific knowledge base article by ID or slug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id_or_slug": {"type": "string", "description": "Article ID or URL slug"},
            },
            "required": ["id_or_slug"],
        },
    },
    {
        "name": "kb_suggest",
        "description": "Propose a new knowledge base article for operator review. Use when you notice a recurring question or discover useful information worth documenting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Article title"},
                "body": {"type": "string", "description": "Article content in markdown"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Relevant tags"},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "query_data_sources",
        "description": "List configured external data sources (MLflow, Kubernetes, Jira, etc.) that this Observatory deployment knows about. Returns metadata including type, endpoint, description, and configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_type": {"type": "string", "description": "Filter by type (e.g. mlflow, kubernetes, jira, artifact_storage)"},
                "status": {"type": "string", "description": "Filter by status (active, inactive)", "default": "active"},
            },
            "required": [],
        },
    },
    {
        "name": "query_jira",
        "description": "Query the configured Jira instance using JQL. Returns issue keys, summaries, statuses, and other fields. Use this to answer questions about Jira tickets, counts, and project contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "jql": {"type": "string", "description": "JQL query (e.g. 'project = RHAIRFE ORDER BY created DESC')"},
                "fields": {"type": "string", "description": "Comma-separated fields to return (default: key,summary,status,issuetype,priority,created)", "default": "key,summary,status,issuetype,priority,created"},
                "max_results": {"type": "integer", "description": "Max issues to return (max 50)", "default": 20},
            },
            "required": ["jql"],
        },
    },
    {
        "name": "browse_files",
        "description": "List files and directories at a given path. Restricted to allowed directories (/app/.context, /app/artifacts). Use this to explore the filesystem structure before reading specific files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list. Examples: /app/.context, /app/artifacts/strace, /app/artifacts/strace/rfe-speedrun-RHAIRFE-2343"},
                "recursive": {"type": "boolean", "description": "If true, list all files recursively (max 100 entries). Prefer non-recursive browsing and drill into subdirectories.", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file. Restricted to allowed directories. Returns up to 10KB by default. Use start_line/end_line to read specific sections of large files (e.g. after finding a line with search_files).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read. Examples: /app/.context/architecture-context/README.md, /app/artifacts/strace/rfe-speedrun-RHAIRFE-2343/trace.log"},
                "start_line": {"type": "integer", "description": "First line to read (1-based). Omit to start from beginning."},
                "end_line": {"type": "integer", "description": "Last line to read (inclusive). Omit to read until 10KB cap."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_stats",
        "description": "Get size, line count, and modification time of a file or directory without reading its content. Useful for checking file size before reading, or getting directory entry counts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path to stat"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for text patterns in files using grep. Restricted to allowed directories. Returns matching lines with file paths and line numbers. Use this to find specific content across many files without reading each one individually.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regex pattern to search for (case-insensitive by default)"},
                "path": {"type": "string", "description": "Directory to search in. Examples: /app/artifacts/strace, /app/.context"},
                "glob": {"type": "string", "description": "File glob to filter (e.g. '*.yaml', '*.md', '*.log'). Omit to search all files."},
                "case_sensitive": {"type": "boolean", "description": "If true, search is case-sensitive", "default": False},
                "max_results": {"type": "integer", "description": "Maximum number of matching lines to return (default 50, max 100)", "default": 50},
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "parse_strace",
        "description": "Parse Linux strace output files to extract structured syscall data. Much faster than grepping strace files manually. Use this for questions about file accesses, commands run, processes spawned, or network connections during a pipeline job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to a strace file or directory of strace files (e.g. /app/artifacts/strace/rfe-speedrun-RHAIRFE-2343)"},
                "query": {
                    "type": "string",
                    "enum": ["files_accessed", "files_written", "execve", "clone", "failed_opens", "network", "summary"],
                    "description": "What to extract: files_accessed (reads), files_written (writes), execve (commands), clone (process/thread spawns), failed_opens (ENOENT etc), network (connections), summary (syscall counts)",
                },
                "filter": {"type": "string", "description": "Optional substring to filter results (e.g. 'architecture-context' to show only matching paths)"},
            },
            "required": ["path", "query"],
        },
    },
    {
        "name": "query_mlflow",
        "description": "Query the configured MLflow tracking server. Search experiments, list runs, or get run metrics. Use this to answer questions about ML experiments, model training, token usage, and costs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search_experiments", "search_runs", "get_run"], "description": "API action to perform"},
                "experiment_name": {"type": "string", "description": "Filter experiments or runs by name pattern"},
                "run_id": {"type": "string", "description": "Specific run ID (for get_run action)"},
                "filter_string": {"type": "string", "description": "MLflow filter string for search_runs (e.g. 'metrics.cost_usd > 0')"},
                "max_results": {"type": "integer", "description": "Max results to return", "default": 20},
            },
            "required": ["action"],
        },
    },
    {
        "name": "query_github",
        "description": (
            "Query the configured GitHub emulator. List repos, branches, commits, "
            "pull requests, read file contents, or search code and issues. "
            "Use this to answer questions about repositories, branches, PRs, "
            "recent commits, or source code in the emulated GitHub instance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_repos", "get_repo", "list_branches",
                        "list_commits", "list_pulls", "get_pull",
                        "get_file", "search_code", "search_issues",
                    ],
                    "description": "API action to perform",
                },
                "owner": {"type": "string", "description": "Repository owner (user or org)"},
                "repo": {"type": "string", "description": "Repository name"},
                "sha": {"type": "string", "description": "Branch name or commit SHA (for list_commits)"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "PR state filter (for list_pulls)", "default": "open"},
                "number": {"type": "integer", "description": "Pull request number (for get_pull)"},
                "path": {"type": "string", "description": "File path (for get_file)"},
                "ref": {"type": "string", "description": "Branch or tag ref (for get_file)"},
                "query": {"type": "string", "description": "Search query (for search_code, search_issues)"},
                "max_results": {"type": "integer", "description": "Max results to return", "default": 20},
            },
            "required": ["action"],
        },
    },
]


async def _handle_query_pipelines(db: aiosqlite.Connection, input: dict) -> dict:
    pipelines = await pipelines_crud.list_pipelines(db)
    status_filter = input.get("status")
    group_filter = input.get("group")
    platform_filter = input.get("platform")
    limit = input.get("limit", 25)

    if status_filter:
        pipelines = [p for p in pipelines if p.get("status") == status_filter]
    if group_filter:
        pipelines = [p for p in pipelines if p.get("group") == group_filter]
    if platform_filter:
        pipelines = [p for p in pipelines if p.get("platform") == platform_filter]

    pipelines = pipelines[:limit]
    summary = [
        {
            "slug": p["slug"],
            "name": p["name"],
            "status": p.get("status"),
            "platform": p.get("platform"),
            "group": p.get("group"),
            "repo_url": p.get("repo_url"),
        }
        for p in pipelines
    ]
    return {"pipelines": summary, "count": len(summary)}


async def _handle_query_runs(db: aiosqlite.Connection, input: dict) -> dict:
    pipeline_slug = input.get("pipeline_slug")
    status_filter = input.get("status")
    per_page = input.get("limit", 20)

    if pipeline_slug:
        pipeline_id = await runs_crud.resolve_pipeline_id(db, pipeline_slug)
        if pipeline_id is None:
            return {"error": f"Pipeline '{pipeline_slug}' not found", "runs": [], "count": 0}
        runs, total = await runs_crud.list_runs(
            db, pipeline_id, page=1, per_page=per_page, status=status_filter,
        )
    else:
        cursor = await db.execute(
            """SELECT pr.*, p.slug as pipeline_slug
            FROM pipeline_runs pr
            JOIN pipelines p ON p.id = pr.pipeline_id
            WHERE (? IS NULL OR pr.status = ?)
            ORDER BY pr.started_at DESC LIMIT ?""",
            (status_filter, status_filter, per_page),
        )
        runs = [dict(r) for r in await cursor.fetchall()]
        total = len(runs)

    summary = [
        {
            "external_id": r.get("external_id"),
            "pipeline_slug": r.get("pipeline_slug", pipeline_slug),
            "status": r.get("status"),
            "started_at": r.get("started_at"),
            "duration_seconds": r.get("duration_seconds"),
            "web_url": r.get("web_url"),
        }
        for r in runs
    ]
    return {"runs": summary, "count": len(summary), "total": total}


async def _handle_query_claims(db: aiosqlite.Connection, input: dict) -> dict:
    result = await claim_triage_crud.list_triage_occurrences(
        db,
        claim_type=input.get("claim_type"),
        exclude_types=[],
        verdict=input.get("verdict"),
        jira_key=input.get("jira_key"),
        search=input.get("search"),
        source=input.get("source"),
        sort=None,
        sort_dir="desc",
        limit=input.get("limit", 20),
        offset=input.get("offset", 0),
        pipeline_slug=input.get("pipeline_slug"),
        occurrence_id=input.get("occurrence_id"),
    )
    occurrences = []
    for occ in result.get("occurrences", []):
        occurrences.append({
            "occurrence_id": occ["id"],
            "normalized_claim_id": occ.get("normalized_claim_id"),
            "claim_text": occ.get("claim_text"),
            "claim_type": occ.get("claim_type"),
            "source_file": occ.get("source_file"),
            "source_locator": occ.get("source_locator"),
            "pipeline_slug": occ.get("pipeline_slug"),
            "jira_keys": occ.get("jira_keys", []),
            "effective_verdict": occ.get("verdict") or "pending",
            "effective_confidence": occ.get("confidence"),
            "effective_severity": occ.get("severity"),
            "effective_verification_run_id": occ.get("verification_run_id"),
            "effective_explanation_run_id": occ.get("explanation_run_id"),
            "override_count": occ.get("override_count", 0),
            "processing_state": occ.get("processing_state"),
            "ui_path": f"/hallucinations?occurrence={occ['id']}",
        })
    return {
        "data_authority": "claim_assurance_v2",
        "occurrences": occurrences,
        "total": result.get("total", 0),
    }


async def _handle_get_claim_occurrence_history(
    db: aiosqlite.Connection, input: dict,
) -> dict:
    occurrence_id = input.get("occurrence_id")
    if occurrence_id is None:
        return {"error": "occurrence_id is required"}
    history = await claim_assurance_crud.get_occurrence_history(db, occurrence_id)
    if history is None:
        return {"error": f"Occurrence {occurrence_id} not found"}
    occ = history["occurrence"]
    verification_runs = history.get("verification_runs", [])
    effective_v_id = history.get("effective_verification_run_id")
    effective_e_id = history.get("effective_explanation_run_id")
    compact_runs = []
    for run in verification_runs:
        compact_run = {
            "id": run["id"],
            "verdict": run["verdict"],
            "confidence": run.get("confidence"),
            "severity": run.get("severity"),
            "evidence_summary": run.get("evidence_summary"),
            "model": run.get("model"),
            "created_at": run.get("created_at"),
            "is_effective": run["id"] == effective_v_id,
            "evidence": run.get("evidence", []),
        }
        explanations = []
        for exp in run.get("explanation_runs", []):
            explanations.append({
                "id": exp["id"],
                "category": exp.get("category"),
                "improvement_target": exp.get("improvement_target"),
                "explanation": exp.get("explanation"),
                "contributing_factors": exp.get("contributing_factors", []),
                "alternative_explanations": exp.get("alternative_explanations", []),
                "remediation": exp.get("remediation"),
                "regression_test": exp.get("regression_test"),
                "human_review_required": exp.get("human_review_required"),
                "created_at": exp.get("created_at"),
                "is_effective": exp["id"] == effective_e_id,
                "evidence": exp.get("evidence", []),
                "regression_runs": exp.get("regression_runs", []),
            })
        compact_run["explanation_runs"] = explanations
        compact_runs.append(compact_run)
    overrides = []
    for ov in history.get("human_overrides", []):
        overrides.append({
            "id": ov["id"],
            "verification_run_id": ov.get("verification_run_id"),
            "actor": ov.get("actor"),
            "decision": ov.get("decision"),
            "rationale": ov.get("rationale"),
            "created_at": ov.get("created_at"),
        })
    return {
        "data_authority": "claim_assurance_v2",
        "occurrence_id": occ["id"],
        "normalized_claim_id": occ.get("normalized_claim_id"),
        "claim_text": occ.get("claim_text"),
        "claim_type": occ.get("claim_type"),
        "source_file": occ.get("source_file"),
        "source_locator": occ.get("source_locator"),
        "pipeline_slug": occ.get("pipeline_slug"),
        "jira_keys": history.get("jira_keys", []),
        "effective_verification_run_id": effective_v_id,
        "effective_explanation_run_id": effective_e_id,
        "processing_state": history.get("processing_state"),
        "verification_runs": compact_runs,
        "human_overrides": overrides,
        "ui_path": f"/hallucinations?occurrence={occ['id']}",
    }


async def _handle_query_claim_explanations(
    db: aiosqlite.Connection, input: dict,
) -> dict:
    result = await claim_triage_crud.list_triage_explanations(
        db,
        category=input.get("category"),
        improvement_target=input.get("improvement_target"),
        jira_key=input.get("jira_key"),
        human_review_required=input.get("human_review_required"),
        limit=input.get("limit", 20),
        offset=input.get("offset", 0),
    )
    explanations = []
    for exp in result.get("explanations", []):
        explanations.append({
            "id": exp["id"],
            "occurrence_id": exp.get("claim_occurrence_id"),
            "claim_text": exp.get("claim_text"),
            "claim_type": exp.get("claim_type"),
            "verdict": exp.get("verdict"),
            "confidence": exp.get("confidence"),
            "severity": exp.get("severity"),
            "source_file": exp.get("source_file"),
            "source_locator": exp.get("source_locator"),
            "category": exp.get("category"),
            "improvement_target": exp.get("improvement_target"),
            "explanation": exp.get("explanation"),
            "contributing_factors": exp.get("contributing_factors", []),
            "alternative_explanations": exp.get("alternative_explanations", []),
            "remediation": exp.get("remediation"),
            "regression_test": exp.get("regression_test"),
            "human_review_required": exp.get("human_review_required"),
            "jira_keys": exp.get("jira_keys", []),
            "evidence": exp.get("evidence", []),
            "created_at": exp.get("created_at"),
        })
    return {
        "data_authority": "claim_assurance_v2",
        "explanations": explanations,
        "total": result.get("total", 0),
    }


async def _handle_get_claim_assurance_summary(
    db: aiosqlite.Connection, _input: dict,
) -> dict:
    summary = await claim_triage_crud.get_triage_summary(db)
    return {
        "data_authority": "claim_assurance_v2",
        "label": "effective_occurrence_summary",
        "total_occurrences": summary.get("total_occurrences", 0),
        "verified": summary.get("verified", 0),
        "pending": summary.get("pending", 0),
        "verdicts": {
            "supported": summary.get("supported", 0),
            "contradicted": summary.get("contradicted", 0),
            "insufficient_evidence": summary.get("insufficient_evidence", 0),
            "not_applicable": summary.get("not_applicable", 0),
        },
        "explained": summary.get("explained", 0),
        "human_review_required": summary.get("human_review_required", 0),
        "jira_keys_referenced": summary.get("jira_keys_referenced", 0),
    }


async def _handle_query_telemetry(db: aiosqlite.Connection, input: dict) -> dict:
    pipeline_slug = input.get("pipeline_slug")

    where = ""
    params: list = []
    if pipeline_slug:
        where = """
            WHERE ts.pipeline_run_id IN (
                SELECT pr.id FROM pipeline_runs pr
                JOIN pipelines p ON p.id = pr.pipeline_id
                WHERE p.slug = ?
            )
        """
        params = [pipeline_slug]

    cursor = await db.execute(
        f"""SELECT
            COALESCE(SUM(ts.total_tokens), 0) as total_tokens,
            COALESCE(SUM(ts.input_tokens), 0) as input_tokens,
            COALESCE(SUM(ts.output_tokens), 0) as output_tokens,
            COALESCE(SUM(ts.cost_usd), 0) as total_cost_usd,
            COUNT(*) as record_count
        FROM telemetry_summaries ts
        {where}""",
        params,
    )
    summary = dict(await cursor.fetchone())

    cursor = await db.execute(
        f"""SELECT ts.model, COUNT(*) as calls, COALESCE(SUM(ts.cost_usd), 0) as cost_usd,
            COALESCE(SUM(ts.total_tokens), 0) as tokens
        FROM telemetry_summaries ts
        {where}
        GROUP BY ts.model ORDER BY cost_usd DESC LIMIT 10""",
        params,
    )
    by_model = [dict(r) for r in await cursor.fetchall()]

    return {"summary": summary, "by_model": by_model}


async def _handle_query_vulnerabilities(db: aiosqlite.Connection, input: dict) -> dict:
    where = []
    params: list = []
    severity = input.get("severity")
    package_name = input.get("package_name")
    limit = input.get("limit", 25)

    if severity:
        where.append("sv.severity = ?")
        params.append(severity.upper())
    if package_name:
        where.append("sv.package_name LIKE ?")
        params.append(f"%{package_name}%")

    where_clause = " AND ".join(where) if where else "1=1"
    cursor = await db.execute(
        f"""SELECT sv.vuln_id, sv.package_name, sv.installed_version,
            sv.fixed_version, sv.severity, cs.image_ref
        FROM sbom_vulnerabilities sv
        JOIN container_sboms cs ON cs.id = sv.sbom_id
        WHERE {where_clause}
        ORDER BY sv.scanned_at DESC LIMIT ?""",
        params + [limit],
    )
    vulns = [dict(r) for r in await cursor.fetchall()]
    return {"vulnerabilities": vulns, "count": len(vulns)}


async def _handle_query_artifacts(db: aiosqlite.Connection, input: dict) -> dict:
    where = []
    params: list = []
    pipeline_slug = input.get("pipeline_slug")
    file_path = input.get("file_path")
    limit = input.get("limit", 25)

    if pipeline_slug:
        where.append("p.slug = ?")
        params.append(pipeline_slug)
    if file_path:
        where.append("ja.file_path LIKE ?")
        params.append(f"%{file_path}%")

    where_clause = " AND ".join(where) if where else "1=1"
    cursor = await db.execute(
        f"""SELECT ja.id, ja.file_path, ja.file_size, ja.mime_type, ja.source,
            ja.created_at, p.slug as pipeline_slug
        FROM job_artifacts ja
        JOIN pipeline_runs pr ON pr.id = ja.pipeline_run_id
        JOIN pipelines p ON p.id = pr.pipeline_id
        WHERE {where_clause}
        ORDER BY ja.created_at DESC LIMIT ?""",
        params + [limit],
    )
    artifacts = [dict(r) for r in await cursor.fetchall()]
    return {"artifacts": artifacts, "count": len(artifacts)}


async def _handle_kb_search(db: aiosqlite.Connection, input: dict) -> dict:
    results = await kb_crud.search_articles(db, input["query"], input.get("limit", 10))
    return {"articles": results, "count": len(results)}


async def _handle_kb_get(db: aiosqlite.Connection, input: dict) -> dict:
    article = await kb_crud.get_article(db, input["id_or_slug"])
    if article:
        return {"article": article}
    return {"error": "Article not found"}


async def _handle_kb_suggest(db: aiosqlite.Connection, input: dict) -> dict:
    article = await kb_crud.create_article(
        db,
        title=input["title"],
        body=input["body"],
        tags=input.get("tags", []),
        status="draft",
        source="agent_suggested",
    )
    return {"article": article, "message": "Article suggested for operator review"}


_MAX_FILE_SIZE = 10 * 1024
_MAX_BROWSE_ENTRIES = 100


def _get_allowed_roots() -> list[Path]:
    from backend.config import settings
    return [Path(p.strip()) for p in settings.chat_browse_roots.split(",") if p.strip()]


def _validate_path(raw: str) -> Path:
    resolved = Path(raw).resolve()
    allowed = _get_allowed_roots()
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError(
            f"Access denied: {raw} is outside allowed directories "
            f"({', '.join(str(r) for r in allowed)})"
        )
    return resolved


async def _handle_browse_files(_db: aiosqlite.Connection, input: dict) -> dict:
    try:
        target = _validate_path(input["path"])
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"Path not found: {input['path']}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {input['path']}. Use read_file to read file contents."}

    entries = []
    if input.get("recursive"):
        for p in sorted(target.rglob("*")):
            if len(entries) >= _MAX_BROWSE_ENTRIES:
                break
            entries.append({
                "path": str(p),
                "type": "dir" if p.is_dir() else "file",
                "size": p.stat().st_size if p.is_file() else None,
            })
    else:
        for p in sorted(target.iterdir()):
            entries.append({
                "path": str(p),
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": p.stat().st_size if p.is_file() else None,
            })

    return {"directory": str(target), "entries": entries, "count": len(entries)}


async def _handle_read_file(_db: aiosqlite.Connection, input: dict) -> dict:
    try:
        target = _validate_path(input["path"])
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"File not found: {input['path']}"}
    if not target.is_file():
        return {"error": f"Not a file: {input['path']}. Use browse_files to list directories."}

    size = target.stat().st_size
    start_line = input.get("start_line")
    end_line = input.get("end_line")

    try:
        if start_line or end_line:
            s = (start_line or 1) - 1
            e = end_line
            with open(target, "r", errors="replace") as f:
                lines = []
                total_chars = 0
                for i, line in enumerate(f):
                    if i < s:
                        continue
                    if e and i >= e:
                        break
                    if total_chars + len(line) > _MAX_FILE_SIZE:
                        lines.append("... [truncated at 10KB cap]")
                        break
                    lines.append(line)
                    total_chars += len(line)
            content = "".join(lines)
            truncated = (e is not None and e < size) or total_chars >= _MAX_FILE_SIZE
            return {
                "path": str(target),
                "size": size,
                "start_line": s + 1,
                "end_line": e or (s + len(lines)),
                "lines_returned": len(lines),
                "truncated": truncated,
                "content": content,
            }
        else:
            content = target.read_text(errors="replace")[:_MAX_FILE_SIZE]
    except Exception as e:
        return {"error": f"Could not read file: {e}"}

    truncated = size > _MAX_FILE_SIZE
    return {
        "path": str(target),
        "size": size,
        "truncated": truncated,
        "content": content,
    }


async def _handle_file_stats(_db: aiosqlite.Connection, input: dict) -> dict:
    try:
        target = _validate_path(input["path"])
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"Path not found: {input['path']}"}

    stat = target.stat()
    result = {
        "path": str(target),
        "type": "dir" if target.is_dir() else "file",
        "size_bytes": stat.st_size,
        "modified": str(os.path.getmtime(target)),
    }

    if target.is_file():
        try:
            with open(target, "r", errors="replace") as f:
                result["line_count"] = sum(1 for _ in f)
        except Exception:
            result["line_count"] = None
        if stat.st_size > 1024 * 1024:
            result["size_human"] = f"{stat.st_size / (1024*1024):.1f}MB"
        elif stat.st_size > 1024:
            result["size_human"] = f"{stat.st_size / 1024:.1f}KB"
        else:
            result["size_human"] = f"{stat.st_size}B"
    elif target.is_dir():
        entries = list(target.iterdir())
        result["entry_count"] = len(entries)
        result["files"] = sum(1 for e in entries if e.is_file())
        result["dirs"] = sum(1 for e in entries if e.is_dir())

    return result


async def _handle_search_files(_db: aiosqlite.Connection, input: dict) -> dict:
    try:
        target = _validate_path(input["path"])
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"Path not found: {input['path']}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {input['path']}"}

    import subprocess

    pattern = input["pattern"]
    max_results = min(input.get("max_results", 50), 100)
    case_sensitive = input.get("case_sensitive", False)

    cmd = ["grep", "-rn", "--binary-files=without-match"]
    if not case_sensitive:
        cmd.append("-i")
    if input.get("glob"):
        cmd.extend(["--include", input["glob"]])
    cmd.extend(["-m", str(max_results * 3), "--", pattern, str(target)])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"error": "Search timed out after 10 seconds. Try a more specific pattern or narrower path."}

    matches = []
    for line in result.stdout.splitlines():
        if len(matches) >= max_results:
            break
        sep = line.find(":")
        if sep == -1:
            continue
        rest = line[sep + 1:]
        sep2 = rest.find(":")
        if sep2 == -1:
            continue
        file_path = line[:sep]
        line_no = rest[:sep2]
        content = rest[sep2 + 1:]
        if len(content) > 200:
            content = content[:200] + "..."
        matches.append({"file": file_path, "line": int(line_no), "text": content.strip()})

    return {
        "pattern": pattern,
        "directory": str(target),
        "matches": matches,
        "count": len(matches),
        "capped": len(result.stdout.splitlines()) > max_results,
    }


async def _handle_parse_strace(_db: aiosqlite.Connection, input: dict) -> dict:
    from backend.chat.strace_parser import parse_strace_path

    try:
        target = _validate_path(input["path"])
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"Path not found: {input['path']}"}

    result = parse_strace_path(target, input["query"])

    filt = input.get("filter")
    if filt and "error" not in result:
        for key in ("files", "commands", "connections", "clones"):
            if key not in result:
                continue
            items = result[key]
            filtered = [
                item for item in items
                if filt in json.dumps(item, default=str)
            ]
            result[key] = filtered
            result["count"] = len(filtered)
            result["filter_applied"] = filt

    return result


async def _resolve_endpoint(db: aiosqlite.Connection, source_type: str) -> str | None:
    sources = await ds_crud.list_data_sources(db, status="active", source_type=source_type)
    if sources and sources[0].get("endpoint"):
        return sources[0]["endpoint"].rstrip("/")
    return None


async def _resolve_source(
    db: aiosqlite.Connection, source_type: str,
) -> tuple[str | None, dict]:
    sources = await ds_crud.list_data_sources(db, status="active", source_type=source_type)
    if sources and sources[0].get("endpoint"):
        return sources[0]["endpoint"].rstrip("/"), sources[0].get("config") or {}
    return None, {}


_MAX_FILE_CONTENT = 10 * 1024


async def _handle_query_github(db: aiosqlite.Connection, input: dict) -> dict:
    endpoint, config = await _resolve_source(db, "github_emulator")
    if not endpoint:
        return {"error": "No active github_emulator data source configured. Add one in Intelligence Settings."}

    action = input.get("action")
    owner = input.get("owner")
    repo = input.get("repo")
    max_results = min(input.get("max_results", 20), 100)

    headers = {}
    token = config.get("token")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        async with httpx.AsyncClient(verify=False, timeout=15, headers=headers) as client:
            if action == "list_repos":
                if not owner:
                    return {"error": "owner is required for list_repos"}
                resp = await client.get(
                    f"{endpoint}/api/v3/users/{owner}/repos",
                    params={"per_page": max_results},
                )
                resp.raise_for_status()
                repos = resp.json()
                return {
                    "repos": [
                        {
                            "full_name": r.get("full_name"),
                            "description": r.get("description"),
                            "default_branch": r.get("default_branch"),
                            "private": r.get("private"),
                            "html_url": r.get("html_url"),
                        }
                        for r in repos[:max_results]
                    ],
                    "count": len(repos[:max_results]),
                }

            elif action == "get_repo":
                if not owner or not repo:
                    return {"error": "owner and repo are required for get_repo"}
                resp = await client.get(f"{endpoint}/api/v3/repos/{owner}/{repo}")
                resp.raise_for_status()
                r = resp.json()
                return {
                    "full_name": r.get("full_name"),
                    "description": r.get("description"),
                    "default_branch": r.get("default_branch"),
                    "private": r.get("private"),
                    "language": r.get("language"),
                    "fork": r.get("fork"),
                    "html_url": r.get("html_url"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                }

            elif action == "list_branches":
                if not owner or not repo:
                    return {"error": "owner and repo are required for list_branches"}
                resp = await client.get(
                    f"{endpoint}/api/v3/repos/{owner}/{repo}/branches",
                    params={"per_page": max_results},
                )
                resp.raise_for_status()
                branches = resp.json()
                return {
                    "branches": [
                        {"name": b.get("name"), "protected": b.get("protected")}
                        for b in branches[:max_results]
                    ],
                    "count": len(branches[:max_results]),
                }

            elif action == "list_commits":
                if not owner or not repo:
                    return {"error": "owner and repo are required for list_commits"}
                params: dict = {"per_page": max_results}
                if input.get("sha"):
                    params["sha"] = input["sha"]
                resp = await client.get(
                    f"{endpoint}/api/v3/repos/{owner}/{repo}/commits",
                    params=params,
                )
                resp.raise_for_status()
                commits = resp.json()
                return {
                    "commits": [
                        {
                            "sha": c.get("sha", "")[:12],
                            "message": (c.get("commit", {}).get("message") or "").split("\n")[0],
                            "author": c.get("commit", {}).get("author", {}).get("name"),
                            "date": c.get("commit", {}).get("author", {}).get("date"),
                        }
                        for c in commits[:max_results]
                    ],
                    "count": len(commits[:max_results]),
                }

            elif action == "list_pulls":
                if not owner or not repo:
                    return {"error": "owner and repo are required for list_pulls"}
                state = input.get("state", "open")
                resp = await client.get(
                    f"{endpoint}/api/v3/repos/{owner}/{repo}/pulls",
                    params={"state": state, "per_page": max_results},
                )
                resp.raise_for_status()
                pulls = resp.json()
                return {
                    "pulls": [
                        {
                            "number": p.get("number"),
                            "title": p.get("title"),
                            "state": p.get("state"),
                            "user": p.get("user", {}).get("login"),
                            "head": p.get("head", {}).get("ref"),
                            "base": p.get("base", {}).get("ref"),
                            "merged": p.get("merged"),
                            "draft": p.get("draft"),
                            "created_at": p.get("created_at"),
                        }
                        for p in pulls[:max_results]
                    ],
                    "count": len(pulls[:max_results]),
                }

            elif action == "get_pull":
                if not owner or not repo:
                    return {"error": "owner and repo are required for get_pull"}
                number = input.get("number")
                if number is None:
                    return {"error": "number is required for get_pull"}
                resp = await client.get(
                    f"{endpoint}/api/v3/repos/{owner}/{repo}/pulls/{number}",
                )
                resp.raise_for_status()
                p = resp.json()
                return {
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "state": p.get("state"),
                    "body": p.get("body"),
                    "user": p.get("user", {}).get("login"),
                    "head": p.get("head", {}).get("ref"),
                    "base": p.get("base", {}).get("ref"),
                    "merged": p.get("merged"),
                    "mergeable": p.get("mergeable"),
                    "draft": p.get("draft"),
                    "created_at": p.get("created_at"),
                    "merged_at": p.get("merged_at"),
                    "changed_files": p.get("changed_files"),
                    "additions": p.get("additions"),
                    "deletions": p.get("deletions"),
                }

            elif action == "get_file":
                if not owner or not repo:
                    return {"error": "owner and repo are required for get_file"}
                file_path = input.get("path")
                if not file_path:
                    return {"error": "path is required for get_file"}
                params = {}
                if input.get("ref"):
                    params["ref"] = input["ref"]
                resp = await client.get(
                    f"{endpoint}/api/v3/repos/{owner}/{repo}/contents/{file_path}",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return {
                        "type": "directory",
                        "path": file_path,
                        "entries": [
                            {"name": e.get("name"), "type": e.get("type"), "size": e.get("size")}
                            for e in data
                        ],
                        "count": len(data),
                    }
                content = None
                truncated = False
                if data.get("encoding") == "base64" and data.get("content"):
                    try:
                        raw = base64.b64decode(data["content"])
                        decoded = raw.decode("utf-8", errors="replace")
                        if len(decoded) > _MAX_FILE_CONTENT:
                            content = decoded[:_MAX_FILE_CONTENT]
                            truncated = True
                        else:
                            content = decoded
                    except Exception:
                        content = None
                return {
                    "type": data.get("type"),
                    "path": data.get("path"),
                    "size": data.get("size"),
                    "content": content,
                    "truncated": truncated,
                }

            elif action == "search_code":
                query = input.get("query")
                if not query:
                    return {"error": "query is required for search_code"}
                resp = await client.get(
                    f"{endpoint}/api/v3/search/code",
                    params={"q": query, "per_page": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "total_count": data.get("total_count", 0),
                    "items": [
                        {
                            "name": item.get("name"),
                            "path": item.get("path"),
                            "repository": item.get("repository", {}).get("full_name"),
                            "html_url": item.get("html_url"),
                        }
                        for item in data.get("items", [])[:max_results]
                    ],
                }

            elif action == "search_issues":
                query = input.get("query")
                if not query:
                    return {"error": "query is required for search_issues"}
                resp = await client.get(
                    f"{endpoint}/api/v3/search/issues",
                    params={"q": query, "per_page": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "total_count": data.get("total_count", 0),
                    "items": [
                        {
                            "number": item.get("number"),
                            "title": item.get("title"),
                            "state": item.get("state"),
                            "user": item.get("user", {}).get("login"),
                            "repository": item.get("repository_url", "").rsplit("/repos/", 1)[-1],
                            "html_url": item.get("html_url"),
                            "created_at": item.get("created_at"),
                        }
                        for item in data.get("items", [])[:max_results]
                    ],
                }

            else:
                return {
                    "error": f"Unknown action: {action}. Use list_repos, get_repo, "
                    "list_branches, list_commits, list_pulls, get_pull, get_file, "
                    "search_code, or search_issues."
                }

    except httpx.HTTPStatusError as e:
        return {"error": f"GitHub emulator returned {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Failed to reach GitHub emulator at {endpoint}: {e}"}


async def _handle_query_jira(db: aiosqlite.Connection, input: dict) -> dict:
    endpoint = await _resolve_endpoint(db, "jira")
    if not endpoint:
        return {"error": "No active Jira data source configured. Add one in Intelligence Settings."}

    jql = input["jql"]
    fields = input.get("fields", "key,summary,status,issuetype,priority,created")
    max_results = min(input.get("max_results", 20), 50)

    try:
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.get(
                f"{endpoint}/rest/api/2/search",
                params={"jql": jql, "fields": fields, "maxResults": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"Jira returned {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Failed to reach Jira at {endpoint}: {e}"}

    issues = []
    for issue in data.get("issues", []):
        f = issue.get("fields", {})
        issues.append({
            "key": issue["key"],
            "summary": f.get("summary"),
            "status": f.get("status", {}).get("name") if isinstance(f.get("status"), dict) else f.get("status"),
            "issuetype": f.get("issuetype", {}).get("name") if isinstance(f.get("issuetype"), dict) else f.get("issuetype"),
            "priority": f.get("priority", {}).get("name") if isinstance(f.get("priority"), dict) else f.get("priority"),
            "created": f.get("created"),
        })
    return {"issues": issues, "total": data.get("total", 0), "count": len(issues)}


async def _handle_query_mlflow(db: aiosqlite.Connection, input: dict) -> dict:
    endpoint = await _resolve_endpoint(db, "mlflow")
    if not endpoint:
        return {"error": "No active MLflow data source configured. Add one in Intelligence Settings."}

    action = input["action"]
    max_results = min(input.get("max_results", 20), 100)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if action == "search_experiments":
                resp = await client.post(
                    f"{endpoint}/api/2.0/mlflow/experiments/search",
                    json={"max_results": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
                experiments = data.get("experiments", [])
                name_filter = input.get("experiment_name", "").lower()
                if name_filter:
                    experiments = [e for e in experiments if name_filter in e.get("name", "").lower()]
                return {
                    "experiments": [
                        {"experiment_id": e.get("experiment_id"), "name": e.get("name"), "lifecycle_stage": e.get("lifecycle_stage")}
                        for e in experiments[:max_results]
                    ],
                    "count": len(experiments),
                }

            elif action == "search_runs":
                body: dict = {"max_results": max_results}
                exp_name = input.get("experiment_name")
                if exp_name:
                    exp_resp = await client.post(
                        f"{endpoint}/api/2.0/mlflow/experiments/search",
                        json={"max_results": 1000},
                    )
                    exp_resp.raise_for_status()
                    exp_ids = [
                        e["experiment_id"]
                        for e in exp_resp.json().get("experiments", [])
                        if exp_name.lower() in e.get("name", "").lower()
                    ]
                    if not exp_ids:
                        return {"runs": [], "count": 0, "error": f"No experiments matching '{exp_name}'"}
                    body["experiment_ids"] = exp_ids
                if input.get("filter_string"):
                    body["filter"] = input["filter_string"]
                resp = await client.post(
                    f"{endpoint}/api/2.0/mlflow/runs/search",
                    json=body,
                )
                resp.raise_for_status()
                runs = resp.json().get("runs", [])
                return {
                    "runs": [
                        {
                            "run_id": r.get("info", {}).get("run_id"),
                            "experiment_id": r.get("info", {}).get("experiment_id"),
                            "status": r.get("info", {}).get("status"),
                            "start_time": r.get("info", {}).get("start_time"),
                            "end_time": r.get("info", {}).get("end_time"),
                            "metrics": {m["key"]: m["value"] for m in r.get("data", {}).get("metrics", [])},
                            "params": {p["key"]: p["value"] for p in r.get("data", {}).get("params", [])},
                        }
                        for r in runs[:max_results]
                    ],
                    "count": len(runs),
                }

            elif action == "get_run":
                run_id = input.get("run_id")
                if not run_id:
                    return {"error": "run_id is required for get_run action"}
                resp = await client.get(
                    f"{endpoint}/api/2.0/mlflow/runs/get",
                    params={"run_id": run_id},
                )
                resp.raise_for_status()
                run = resp.json().get("run", {})
                return {
                    "run": {
                        "run_id": run.get("info", {}).get("run_id"),
                        "experiment_id": run.get("info", {}).get("experiment_id"),
                        "status": run.get("info", {}).get("status"),
                        "start_time": run.get("info", {}).get("start_time"),
                        "end_time": run.get("info", {}).get("end_time"),
                        "metrics": {m["key"]: m["value"] for m in run.get("data", {}).get("metrics", [])},
                        "params": {p["key"]: p["value"] for p in run.get("data", {}).get("params", [])},
                    }
                }

            else:
                return {"error": f"Unknown action: {action}. Use search_experiments, search_runs, or get_run."}

    except httpx.HTTPStatusError as e:
        return {"error": f"MLflow returned {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Failed to reach MLflow at {endpoint}: {e}"}


async def _handle_query_data_sources(db: aiosqlite.Connection, input: dict) -> dict:
    sources = await ds_crud.list_data_sources(
        db,
        status=input.get("status"),
        source_type=input.get("source_type"),
    )
    summary = [
        {
            "name": s["name"],
            "source_type": s["source_type"],
            "endpoint": s.get("endpoint"),
            "description": s.get("description"),
            "status": s["status"],
            "config": s.get("config", {}),
        }
        for s in sources
    ]
    return {"data_sources": summary, "count": len(summary)}


_TOOL_HANDLERS = {
    "query_pipelines": _handle_query_pipelines,
    "query_runs": _handle_query_runs,
    "query_claims": _handle_query_claims,
    "get_claim_occurrence_history": _handle_get_claim_occurrence_history,
    "query_claim_explanations": _handle_query_claim_explanations,
    "get_claim_assurance_summary": _handle_get_claim_assurance_summary,
    "query_telemetry": _handle_query_telemetry,
    "query_vulnerabilities": _handle_query_vulnerabilities,
    "query_artifacts": _handle_query_artifacts,
    "kb_search": _handle_kb_search,
    "kb_get": _handle_kb_get,
    "kb_suggest": _handle_kb_suggest,
    "query_data_sources": _handle_query_data_sources,
    "query_jira": _handle_query_jira,
    "query_github": _handle_query_github,
    "query_mlflow": _handle_query_mlflow,
    "browse_files": _handle_browse_files,
    "read_file": _handle_read_file,
    "search_files": _handle_search_files,
    "file_stats": _handle_file_stats,
    "parse_strace": _handle_parse_strace,
}


async def execute_tool(db: aiosqlite.Connection, name: str, tool_input: dict) -> str:
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = await handler(db, tool_input)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
