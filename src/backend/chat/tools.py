from __future__ import annotations

import json

import aiosqlite

from backend.crud import data_sources as ds_crud
from backend.crud import hallucinations as claims_crud
from backend.crud import kb as kb_crud
from backend.crud import pipelines as pipelines_crud
from backend.crud import runs as runs_crud


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
        "description": "Search verified factual claims extracted from pipeline outputs. Filter by claim type, verdict, or text search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Text search in claim content"},
                "claim_type": {"type": "string", "description": "Filter by claim type"},
                "verdict": {"type": "string", "description": "Filter by verdict (supported, refuted, insufficient, inconclusive)"},
                "pipeline_slug": {"type": "string", "description": "Filter claims from a specific pipeline"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
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
    result = await claims_crud.get_claims(
        db,
        search=input.get("search"),
        claim_type=input.get("claim_type"),
        verdict=input.get("verdict"),
        pipeline_slug=input.get("pipeline_slug"),
        limit=input.get("limit", 20),
        offset=0,
    )
    return {"claims": result.get("claims", []), "total": result.get("total", 0)}


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
    "query_telemetry": _handle_query_telemetry,
    "query_vulnerabilities": _handle_query_vulnerabilities,
    "query_artifacts": _handle_query_artifacts,
    "kb_search": _handle_kb_search,
    "kb_get": _handle_kb_get,
    "kb_suggest": _handle_kb_suggest,
    "query_data_sources": _handle_query_data_sources,
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
