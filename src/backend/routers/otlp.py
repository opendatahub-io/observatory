"""OTLP HTTP JSON receiver for /v1/traces.

Accepts the standard OTLP HTTP JSON format (application/json) and stores
spans in the telemetry_spans table. Correlates spans to pipelines by
matching ``service.name`` against ``pipelines.slug``.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Request  # noqa: F401

from backend.auth import require_api_key_scoped
from backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["otlp"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_resource_attr(resource: dict | None, key: str) -> str | None:
    """Pull a string attribute value out of an OTLP resource dict."""
    if not resource:
        return None
    for attr in resource.get("attributes", []):
        if attr.get("key") == key:
            value = attr.get("value", {})
            # Try common OTLP value wrappers
            return (
                value.get("stringValue")
                or value.get("intValue")
                or value.get("doubleValue")
            )
    return None


def _attr_value(value: dict) -> Any:
    """Return the python value from an OTLP attribute value wrapper."""
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        # intValue may be a string representation of an int
        try:
            return int(value["intValue"])
        except (ValueError, TypeError):
            return value["intValue"]
    if "doubleValue" in value:
        return value["doubleValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "arrayValue" in value:
        return [_attr_value(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return {
            kv["key"]: _attr_value(kv["value"])
            for kv in value["kvlistValue"].get("values", [])
        }
    return None


def _attrs_to_dict(attributes: list[dict]) -> dict:
    """Convert OTLP attribute list to a flat dict."""
    result: dict = {}
    for attr in attributes:
        key = attr.get("key")
        value = attr.get("value", {})
        if key:
            result[key] = _attr_value(value)
    return result


def _nano_to_iso(nano: str | int | None) -> str | None:
    """Convert nanosecond unix timestamp to ISO 8601 string."""
    if nano is None:
        return None
    try:
        ns = int(nano)
    except (ValueError, TypeError):
        return None
    if ns == 0:
        return None
    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return dt.isoformat()


def _compute_duration_ms(start_nano: str | int | None, end_nano: str | int | None) -> int | None:
    """Compute duration in milliseconds from nanosecond timestamps."""
    if start_nano is None or end_nano is None:
        return None
    try:
        start = int(start_nano)
        end = int(end_nano)
    except (ValueError, TypeError):
        return None
    if start == 0 or end == 0:
        return None
    return int((end - start) / 1e6)


def _status_code_str(status: dict | None) -> str | None:
    """Map OTLP status code integer to a human-readable string."""
    if not status:
        return None
    code = status.get("code")
    if code is None:
        return None
    mapping = {0: "UNSET", 1: "OK", 2: "ERROR"}
    return mapping.get(code, str(code))


# ---------------------------------------------------------------------------
# Pipeline correlation
# ---------------------------------------------------------------------------

async def _find_pipeline_id(db: aiosqlite.Connection, service_name: str | None) -> int | None:
    """Look up a pipeline by matching service_name to pipelines.slug."""
    if not service_name:
        return None
    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = ?", (service_name,)
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def _find_or_create_run(
    db: aiosqlite.Connection, pipeline_id: int, trace_id: str
) -> int:
    """Find an existing pipeline_run for this trace, or create one.

    We use the trace_id as the external_id to group all spans of a trace
    under a single pipeline_run.
    """
    cursor = await db.execute(
        "SELECT id FROM pipeline_runs WHERE pipeline_id = ? AND external_id = ?",
        (pipeline_id, trace_id),
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    cursor = await db.execute(
        "INSERT INTO pipeline_runs (pipeline_id, external_id, status) VALUES (?, ?, ?)",
        (pipeline_id, trace_id, "trace"),
    )
    await db.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Telemetry summary extraction
# ---------------------------------------------------------------------------

_TOKEN_PROMPT_KEYS = {"llm.token_count.prompt", "gen_ai.usage.input_tokens"}
_TOKEN_COMPLETION_KEYS = {"llm.token_count.completion", "gen_ai.usage.output_tokens"}
_COST_KEYS = {"gen_ai.usage.cost"}
_MODEL_KEYS = {"gen_ai.request.model", "llm.request.model"}


def _extract_telemetry(attrs: dict) -> dict | None:
    """Extract token / cost / model info from span attributes if present."""
    input_tokens = None
    output_tokens = None
    cost_usd = None
    model = None

    for key, value in attrs.items():
        if key in _TOKEN_PROMPT_KEYS and input_tokens is None:
            try:
                input_tokens = int(value)
            except (ValueError, TypeError):
                pass
        elif key in _TOKEN_COMPLETION_KEYS and output_tokens is None:
            try:
                output_tokens = int(value)
            except (ValueError, TypeError):
                pass
        elif key in _COST_KEYS and cost_usd is None:
            try:
                cost_usd = float(value)
            except (ValueError, TypeError):
                pass
        elif key in _MODEL_KEYS and model is None:
            model = str(value)

    # Only return if we found at least something interesting
    if input_tokens is None and output_tokens is None and cost_usd is None and model is None:
        return None

    total_tokens = None
    if input_tokens is not None or output_tokens is not None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

    return {
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "model": model,
    }


async def _upsert_telemetry_summary(
    db: aiosqlite.Connection,
    pipeline_run_id: int,
    telemetry: dict,
    operation_name: str | None,
    duration_ms: int | None,
) -> None:
    """Insert a telemetry_summary row for the span."""
    await db.execute(
        """INSERT INTO telemetry_summaries
           (pipeline_run_id, total_tokens, input_tokens, output_tokens,
            cost_usd, model, skill_name, duration_ms, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pipeline_run_id,
            telemetry.get("total_tokens"),
            telemetry.get("input_tokens"),
            telemetry.get("output_tokens"),
            telemetry.get("cost_usd"),
            telemetry.get("model"),
            operation_name,
            duration_ms,
            "otlp",
        ),
    )


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@router.post("/v1/traces")
async def receive_traces(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    """Receive OTLP HTTP JSON traces and store spans."""
    api_key = request.headers.get("x-api-key")

    try:
        body = await request.json()
    except Exception:
        # Malformed / empty body — return 200 per OTLP spec
        return {}

    if not isinstance(body, dict):
        return {}

    resource_spans = body.get("resourceSpans", [])
    if not isinstance(resource_spans, list):
        return {}

    # Extract the first service.name for scope checking
    first_service_name = None
    for rs in resource_spans:
        if isinstance(rs, dict):
            resource = rs.get("resource", {})
            sn = _extract_resource_attr(resource, "service.name")
            if sn:
                first_service_name = sn
                break

    # Auth check with scope
    await require_api_key_scoped(first_service_name, api_key, db)

    for rs in resource_spans:
        if not isinstance(rs, dict):
            continue

        resource = rs.get("resource", {})
        service_name = _extract_resource_attr(resource, "service.name")

        # Pipeline correlation
        pipeline_id = await _find_pipeline_id(db, service_name)

        scope_spans_list = rs.get("scopeSpans", [])
        if not isinstance(scope_spans_list, list):
            continue

        for ss in scope_spans_list:
            if not isinstance(ss, dict):
                continue

            spans = ss.get("spans", [])
            if not isinstance(spans, list):
                continue

            for span in spans:
                if not isinstance(span, dict):
                    continue

                trace_id = span.get("traceId", "")
                span_id = span.get("spanId", "")
                parent_span_id = span.get("parentSpanId", "")
                operation_name = span.get("name", "")
                start_nano = span.get("startTimeUnixNano")
                end_nano = span.get("endTimeUnixNano")
                status = span.get("status")
                raw_attrs = span.get("attributes", [])

                start_time = _nano_to_iso(start_nano)
                end_time = _nano_to_iso(end_nano)
                duration_ms = _compute_duration_ms(start_nano, end_nano)
                status_code = _status_code_str(status)

                attrs_dict = _attrs_to_dict(raw_attrs) if isinstance(raw_attrs, list) else {}
                attrs_json = json.dumps(attrs_dict) if attrs_dict else None

                # Determine pipeline_run_id
                pipeline_run_id = None
                if pipeline_id and trace_id:
                    pipeline_run_id = await _find_or_create_run(
                        db, pipeline_id, trace_id
                    )

                await db.execute(
                    """INSERT INTO telemetry_spans
                       (pipeline_run_id, trace_id, span_id, parent_span_id,
                        operation_name, service_name,
                        start_time, end_time, duration_ms,
                        status_code, attributes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pipeline_run_id,
                        trace_id,
                        span_id,
                        parent_span_id or None,
                        operation_name or None,
                        service_name,
                        start_time,
                        end_time,
                        duration_ms,
                        status_code,
                        attrs_json,
                    ),
                )

                # Telemetry summary extraction
                if pipeline_run_id and attrs_dict:
                    telemetry = _extract_telemetry(attrs_dict)
                    if telemetry:
                        await _upsert_telemetry_summary(
                            db, pipeline_run_id, telemetry, operation_name, duration_ms
                        )

    await db.commit()
    return {}


# ---------------------------------------------------------------------------
# Span query endpoint (trace explorer)
# ---------------------------------------------------------------------------

@router.get("/api/telemetry/spans/{run_id}")
async def get_spans_for_run(
    run_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    """Return all spans for a given pipeline run, ordered by start_time."""
    cursor = await db.execute(
        """SELECT id, pipeline_run_id, trace_id, span_id, parent_span_id,
                  operation_name, service_name,
                  start_time, end_time, duration_ms,
                  status_code, attributes, created_at
           FROM telemetry_spans
           WHERE pipeline_run_id = ?
           ORDER BY start_time""",
        (run_id,),
    )
    rows = await cursor.fetchall()
    spans = []
    for row in rows:
        spans.append({
            "id": row["id"],
            "pipeline_run_id": row["pipeline_run_id"],
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "parent_span_id": row["parent_span_id"],
            "operation_name": row["operation_name"],
            "service_name": row["service_name"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "duration_ms": row["duration_ms"],
            "status_code": row["status_code"],
            "attributes": row["attributes"],
            "created_at": row["created_at"],
        })
    return {"spans": spans}
