import json

import aiosqlite


TRIAGE_CTES = """
WITH latest_verification AS (
    SELECT cvr.*
    FROM claim_verification_runs cvr
    WHERE cvr.id = (
        SELECT newer.id FROM claim_verification_runs newer
        WHERE newer.claim_occurrence_id = cvr.claim_occurrence_id
        ORDER BY newer.created_at DESC, newer.id DESC LIMIT 1
    )
),
latest_explanation AS (
    SELECT cer.*
    FROM claim_explanation_runs cer
    WHERE cer.id = (
        SELECT newer.id FROM claim_explanation_runs newer
        WHERE newer.verification_run_id = cer.verification_run_id
        ORDER BY newer.created_at DESC, newer.id DESC LIMIT 1
    )
)
"""


def _processing_state(row: dict) -> str:
    if row.get("verification_run_id") is None:
        return "not_verified"
    if row.get("explanation_run_id") is None:
        return "verified_without_explanation"
    if row.get("human_review_required") == 1:
        return "explanation_requires_human_review"
    return "explained"


async def _jira_keys(db: aiosqlite.Connection, occurrence_id: int) -> list[str]:
    cursor = await db.execute(
        """SELECT jira_key FROM claim_occurrence_jira_keys
           WHERE claim_occurrence_id = ? ORDER BY jira_key""",
        (occurrence_id,),
    )
    return [row["jira_key"] for row in await cursor.fetchall()]


async def get_triage_summary(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute(
        TRIAGE_CTES +
        """SELECT COUNT(*) AS total_occurrences,
                  COUNT(lv.id) AS verified,
                  COALESCE(SUM(CASE WHEN lv.id IS NULL THEN 1 ELSE 0 END), 0) AS pending,
                  COALESCE(SUM(CASE WHEN lv.verdict = 'supported' THEN 1 ELSE 0 END), 0) AS supported,
                  COALESCE(SUM(CASE WHEN lv.verdict = 'contradicted' THEN 1 ELSE 0 END), 0) AS contradicted,
                  COALESCE(SUM(CASE WHEN lv.verdict = 'insufficient_evidence' THEN 1 ELSE 0 END), 0)
                    AS insufficient_evidence,
                  COALESCE(SUM(CASE WHEN lv.verdict = 'not_applicable' THEN 1 ELSE 0 END), 0)
                    AS not_applicable,
                  COUNT(le.id) AS explained,
                  COALESCE(SUM(CASE WHEN le.human_review_required = 1 THEN 1 ELSE 0 END), 0)
                    AS human_review_required
           FROM claim_occurrences co
           LEFT JOIN latest_verification lv ON lv.claim_occurrence_id = co.id
           LEFT JOIN latest_explanation le ON le.verification_run_id = lv.id
           WHERE co.accepted = 1"""
    )
    result = dict(await cursor.fetchone())
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT jira_key) AS count FROM claim_occurrence_jira_keys"
    )
    result["jira_keys_referenced"] = (await cursor.fetchone())["count"]
    return result


async def get_triage_types(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """SELECT claim_type, COUNT(*) AS count FROM claim_occurrences
           WHERE accepted = 1 GROUP BY claim_type ORDER BY count DESC"""
    )
    return [dict(row) for row in await cursor.fetchall()]


TRIAGE_SORT_COLUMNS = {
    "claim": "co.claim_text",
    "type": "co.claim_type",
    "verdict": "COALESCE(lv.verdict, 'pending')",
    "confidence": "COALESCE(lv.confidence, -1)",
    "jira": "jira_count",
    "source": "cer.source_file",
}


async def list_triage_occurrences(
    db: aiosqlite.Connection,
    claim_type: str | None,
    exclude_types: list[str],
    verdict: str | None,
    jira_key: str | None,
    search: str | None,
    source: str | None,
    sort: str | None,
    sort_dir: str,
    limit: int,
    offset: int,
    pipeline_slug: str | None = None,
    occurrence_id: int | None = None,
) -> dict:
    where = ["co.accepted = 1"]
    params: list[object] = []
    if claim_type:
        where.append("co.claim_type = ?")
        params.append(claim_type)
    if exclude_types:
        placeholders = ",".join("?" for _ in exclude_types)
        where.append(f"co.claim_type NOT IN ({placeholders})")
        params.extend(exclude_types)
    if verdict:
        if verdict == "pending":
            where.append("lv.id IS NULL")
        else:
            where.append("lv.verdict = ?")
            params.append(verdict)
    if jira_key:
        where.append(
            "EXISTS (SELECT 1 FROM claim_occurrence_jira_keys cojk "
            "WHERE cojk.claim_occurrence_id = co.id AND cojk.jira_key = ?)"
        )
        params.append(jira_key.upper())
    if search:
        if search.isdigit():
            where.append("co.id = ?")
            params.append(int(search))
        else:
            where.append("co.claim_text LIKE ?")
            params.append(f"%{search}%")
    if source:
        where.append("cer.source_file LIKE ?")
        params.append(f"%{source}%")
    if pipeline_slug:
        where.append("cer.pipeline_slug = ?")
        params.append(pipeline_slug)
    if occurrence_id is not None:
        where.append("co.id = ?")
        params.append(occurrence_id)

    where_sql = " AND ".join(where)
    cursor = await db.execute(
        TRIAGE_CTES + f"""SELECT COUNT(*) AS count
            FROM claim_occurrences co
            JOIN claim_source_units csu ON csu.id = co.source_unit_id
            JOIN claim_extraction_runs cer ON cer.id = csu.extraction_run_id
            LEFT JOIN latest_verification lv ON lv.claim_occurrence_id = co.id
            LEFT JOIN latest_explanation le ON le.verification_run_id = lv.id
            WHERE {where_sql}""",  # noqa: S608
        params,
    )
    total = (await cursor.fetchone())["count"]
    direction = "DESC" if sort_dir == "desc" else "ASC"
    order = TRIAGE_SORT_COLUMNS.get(sort or "", "co.id")
    cursor = await db.execute(
        TRIAGE_CTES + f"""SELECT co.id, co.normalized_claim_id, co.claim_text,
                  co.original_text, co.claim_type, co.modality, co.product_version,
                  co.temporal_scope, c.claim_hash, csu.source_locator,
                  cer.source_file, cer.pipeline_slug, cer.artifact_type,
                  membership.canonical_group_id, canonical.canonical_text,
                  lv.id AS verification_run_id, lv.verdict, lv.severity,
                  lv.confidence, lv.evidence_summary, lv.created_at AS verified_at,
                  le.id AS explanation_run_id, le.category AS explanation_category,
                  le.improvement_target, le.human_review_required,
                  (SELECT COUNT(*) FROM claim_occurrence_jira_keys cojk
                   WHERE cojk.claim_occurrence_id = co.id) AS jira_count,
                  (SELECT COUNT(*) FROM claim_human_overrides cho
                   WHERE cho.claim_occurrence_id = co.id) AS override_count
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
            LEFT JOIN latest_verification lv ON lv.claim_occurrence_id = co.id
            LEFT JOIN latest_explanation le ON le.verification_run_id = lv.id
            WHERE {where_sql}
            ORDER BY {order} {direction}, co.id DESC LIMIT ? OFFSET ?""",  # noqa: S608
        [*params, limit, offset],
    )
    occurrences = []
    for row in await cursor.fetchall():
        occurrence = dict(row)
        occurrence["jira_keys"] = await _jira_keys(db, occurrence["id"])
        occurrence["processing_state"] = _processing_state(occurrence)
        occurrences.append(occurrence)
    return {"occurrences": occurrences, "total": total}


async def get_triage_issues(
    db: aiosqlite.Connection, sort: str, sort_dir: str, limit: int, offset: int
) -> dict:
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT jira_key) AS count FROM claim_occurrence_jira_keys"
    )
    total = (await cursor.fetchone())["count"]
    allowed = {
        "jira_key", "total_occurrences", "supported", "contradicted",
        "insufficient_evidence", "not_applicable", "pending",
    }
    order = sort if sort in allowed else "contradicted"
    direction = "DESC" if sort_dir == "desc" else "ASC"
    cursor = await db.execute(
        TRIAGE_CTES + f"""SELECT cojk.jira_key,
                  COUNT(*) AS total_occurrences,
                  SUM(CASE WHEN lv.verdict = 'supported' THEN 1 ELSE 0 END) AS supported,
                  SUM(CASE WHEN lv.verdict = 'contradicted' THEN 1 ELSE 0 END) AS contradicted,
                  SUM(CASE WHEN lv.verdict = 'insufficient_evidence' THEN 1 ELSE 0 END)
                    AS insufficient_evidence,
                  SUM(CASE WHEN lv.verdict = 'not_applicable' THEN 1 ELSE 0 END)
                    AS not_applicable,
                  SUM(CASE WHEN lv.id IS NULL THEN 1 ELSE 0 END) AS pending
           FROM claim_occurrence_jira_keys cojk
           JOIN claim_occurrences co ON co.id = cojk.claim_occurrence_id
           LEFT JOIN latest_verification lv ON lv.claim_occurrence_id = co.id
           WHERE co.accepted = 1 GROUP BY cojk.jira_key
           ORDER BY {order} {direction}, cojk.jira_key ASC LIMIT ? OFFSET ?""",  # noqa: S608
        (limit, offset),
    )
    return {"issues": [dict(row) for row in await cursor.fetchall()], "total": total}


async def list_triage_explanations(
    db: aiosqlite.Connection,
    category: str | None,
    improvement_target: str | None,
    jira_key: str | None,
    human_review_required: bool | None,
    limit: int,
    offset: int,
) -> dict:
    where = ["1=1"]
    params: list[object] = []
    if category:
        where.append("cer.category = ?")
        params.append(category)
    if improvement_target:
        where.append("cer.improvement_target = ?")
        params.append(improvement_target)
    if jira_key:
        where.append(
            "EXISTS (SELECT 1 FROM claim_occurrence_jira_keys cojk "
            "WHERE cojk.claim_occurrence_id = co.id AND cojk.jira_key = ?)"
        )
        params.append(jira_key.upper())
    if human_review_required is not None:
        where.append("cer.human_review_required = ?")
        params.append(human_review_required)
    where_sql = " AND ".join(where)
    joins = """FROM claim_explanation_runs cer
        JOIN claim_verification_runs cvr ON cvr.id = cer.verification_run_id
        JOIN claim_occurrences co ON co.id = cvr.claim_occurrence_id
        JOIN claim_source_units csu ON csu.id = co.source_unit_id
        JOIN claim_extraction_runs extraction ON extraction.id = csu.extraction_run_id"""
    cursor = await db.execute(
        f"SELECT COUNT(*) AS count {joins} WHERE {where_sql}",  # noqa: S608
        params,
    )
    total = (await cursor.fetchone())["count"]
    cursor = await db.execute(
        f"""SELECT cer.*, cvr.claim_occurrence_id, cvr.verdict, cvr.confidence,
                   cvr.severity, co.claim_text, co.claim_type, csu.source_locator,
                   extraction.source_file
            {joins} WHERE {where_sql}
            ORDER BY cer.created_at DESC, cer.id DESC LIMIT ? OFFSET ?""",  # noqa: S608
        [*params, limit, offset],
    )
    explanations = []
    for row in await cursor.fetchall():
        explanation = dict(row)
        for field in ("contributing_factors", "alternative_explanations"):
            try:
                explanation[field] = json.loads(explanation.get(field) or "[]")
            except json.JSONDecodeError:
                explanation[field] = []
        explanation["jira_keys"] = await _jira_keys(
            db, explanation["claim_occurrence_id"]
        )
        evidence_cursor = await db.execute(
            """SELECT * FROM claim_evidence_records
               WHERE stage = 'explanation' AND stage_run_id = ? ORDER BY id""",
            (explanation["id"],),
        )
        explanation["evidence"] = [
            dict(evidence) for evidence in await evidence_cursor.fetchall()
        ]
        explanations.append(explanation)
    return {"explanations": explanations, "total": total}


async def get_triage_explanation_facets(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute(
        """SELECT category AS value, COUNT(*) AS count FROM claim_explanation_runs
           GROUP BY category ORDER BY count DESC, category"""
    )
    categories = [dict(row) for row in await cursor.fetchall()]
    cursor = await db.execute(
        """SELECT improvement_target AS value, COUNT(*) AS count
           FROM claim_explanation_runs WHERE improvement_target IS NOT NULL
           GROUP BY improvement_target ORDER BY count DESC, improvement_target"""
    )
    return {
        "categories": categories,
        "improvement_targets": [dict(row) for row in await cursor.fetchall()],
    }
