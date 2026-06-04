"""Parser for OTEL summary artifacts into telemetry_summaries rows."""

from __future__ import annotations

import aiosqlite


_EXISTS_SQL = """
SELECT 1 FROM telemetry_summaries
WHERE pipeline_run_id = ?
  AND total_tokens IS ?
  AND input_tokens IS ?
  AND output_tokens IS ?
  AND cost_usd IS ?
  AND model IS ?
  AND skill_name IS ?
  AND duration_ms IS ?
  AND source = 'artifact'
LIMIT 1
"""

_INSERT_SQL = """
INSERT INTO telemetry_summaries
    (pipeline_run_id, total_tokens, input_tokens, output_tokens,
     cost_usd, model, skill_name, duration_ms, source)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'artifact')
"""


async def parse_otel_summary(
    db: aiosqlite.Connection,
    pipeline_run_id: int,
    data: dict,
) -> int:
    """Parse an OTEL summary artifact and insert into telemetry_summaries.

    Supports two formats:
      - Format A (flat): top-level fields (total_tokens, cost_usd, etc.)
      - Format B (per-skill): a ``skills`` list of dicts, each with the same fields
        plus ``skill_name``.

    Returns the number of summary rows inserted.
    """
    if not isinstance(data, dict):
        return 0

    skills = data.get("skills")
    if isinstance(skills, list) and skills:
        entries = skills
    else:
        # Flat format: only attempt insertion if at least one relevant field exists
        relevant_keys = {
            "total_tokens", "input_tokens", "output_tokens",
            "cost_usd", "model", "skill_name", "duration_ms",
        }
        if not relevant_keys & set(data.keys()):
            return 0
        entries = [data]

    inserted = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        params = (
            pipeline_run_id,
            entry.get("total_tokens"),
            entry.get("input_tokens"),
            entry.get("output_tokens"),
            entry.get("cost_usd"),
            entry.get("model"),
            entry.get("skill_name"),
            entry.get("duration_ms"),
        )
        # Check for existing duplicate row before inserting
        cursor = await db.execute(_EXISTS_SQL, params)
        existing = await cursor.fetchone()
        if existing:
            continue
        await db.execute(_INSERT_SQL, params)
        inserted += 1

    await db.commit()
    return inserted
