import aiosqlite


async def get_hallucination_summary(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute("SELECT COUNT(*) as total FROM claims")
    total = (await cursor.fetchone())["total"]

    cursor = await db.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_verdicts")
    verified = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_verdicts WHERE verdict = 'refuted'")
    refuted = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_verdicts WHERE verdict = 'supported'")
    supported = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_verdicts WHERE verdict = 'inconclusive'")
    inconclusive = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT jira_key) FROM claim_jira_keys")
    jira_keys = (await cursor.fetchone())[0]

    return {
        "total_claims": total,
        "verified": verified,
        "pending": total - verified,
        "supported": supported,
        "refuted": refuted,
        "inconclusive": inconclusive,
        "jira_keys_referenced": jira_keys,
    }


async def get_claims_by_type(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT claim_type, COUNT(*) as count FROM claims GROUP BY claim_type ORDER BY count DESC"
    )
    return [dict(r) for r in await cursor.fetchall()]


SORT_COLUMNS = {
    "claim": "c.claim_text",
    "type": "c.claim_type",
    "confidence": "confidence_val",
    "jira": "jira_count",
    "sources": "source_count",
}


async def get_claims(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    claim_type: str | None = None,
    exclude_types: list[str] | None = None,
    verdict: str | None = None,
    jira_key: str | None = None,
    search: str | None = None,
    sort: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    where = []
    params: list = []

    if pipeline_slug:
        where.append("cs.pipeline_slug = ?")
        params.append(pipeline_slug)
    if claim_type:
        where.append("c.claim_type = ?")
        params.append(claim_type)
    if exclude_types:
        placeholders = ",".join("?" for _ in exclude_types)
        where.append(f"c.claim_type NOT IN ({placeholders})")
        params.extend(exclude_types)
    if search:
        where.append("c.claim_text LIKE ?")
        params.append(f"%{search}%")
    if jira_key:
        where.append("c.id IN (SELECT claim_id FROM claim_jira_keys WHERE jira_key = ?)")
        params.append(jira_key)
    if verdict:
        if verdict == "pending":
            where.append("c.id NOT IN (SELECT claim_id FROM claim_verdicts)")
        else:
            where.append("c.id IN (SELECT claim_id FROM claim_verdicts WHERE verdict = ?)")
            params.append(verdict)

    where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"""
        SELECT COUNT(DISTINCT c.id) FROM claims c
        LEFT JOIN claim_sources cs ON cs.claim_id = c.id
        WHERE {where_clause}
    """
    cursor = await db.execute(count_sql, params)
    total = (await cursor.fetchone())[0]

    order_dir = "DESC" if sort_dir == "desc" else "ASC"
    order_col = SORT_COLUMNS.get(sort or "", "c.id")
    if order_col == "c.id":
        order_dir = "DESC"

    query_sql = f"""
        SELECT c.id, c.claim_text, c.claim_type, c.claim_hash, c.first_seen_at,
            (SELECT COUNT(*) FROM claim_jira_keys WHERE claim_id = c.id) as jira_count,
            (SELECT COUNT(*) FROM claim_sources WHERE claim_id = c.id) as source_count,
            COALESCE((SELECT confidence FROM claim_verdicts WHERE claim_id = c.id ORDER BY verified_at DESC LIMIT 1), -1) as confidence_val
        FROM claims c
        LEFT JOIN claim_sources cs ON cs.claim_id = c.id
        WHERE {where_clause}
        GROUP BY c.id
        ORDER BY {order_col} {order_dir}
        LIMIT ? OFFSET ?
    """
    cursor = await db.execute(query_sql, params + [limit, offset])
    claims = [dict(r) for r in await cursor.fetchall()]

    for claim in claims:
        cid = claim["id"]

        cursor = await db.execute(
            "SELECT pipeline_slug, source_file FROM claim_sources WHERE claim_id = ? ORDER BY extracted_at DESC",
            (cid,),
        )
        claim["sources"] = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute("SELECT jira_key FROM claim_jira_keys WHERE claim_id = ?", (cid,))
        claim["jira_keys"] = [r["jira_key"] for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT verdict, confidence, evidence_summary, evidence_source, verified_at FROM claim_verdicts WHERE claim_id = ? ORDER BY verified_at DESC LIMIT 1",
            (cid,),
        )
        verdict_row = await cursor.fetchone()
        claim["verdict"] = dict(verdict_row) if verdict_row else None

    return {"claims": claims, "total": total}


async def get_claim_detail(db: aiosqlite.Connection, claim_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
    row = await cursor.fetchone()
    if not row:
        return None

    claim = dict(row)

    cursor = await db.execute(
        "SELECT pipeline_slug, source_file, original_text, extracted_at FROM claim_sources WHERE claim_id = ?",
        (claim_id,),
    )
    claim["sources"] = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT jira_key FROM claim_jira_keys WHERE claim_id = ?", (claim_id,))
    claim["jira_keys"] = [r["jira_key"] for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM claim_verdicts WHERE claim_id = ? ORDER BY verified_at DESC",
        (claim_id,),
    )
    claim["verdicts"] = [dict(r) for r in await cursor.fetchall()]

    return claim


async def get_pipeline_hallucination_summary(db: aiosqlite.Connection, pipeline_slug: str) -> dict:
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT claim_id) FROM claim_sources WHERE pipeline_slug = ?",
        (pipeline_slug,),
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute("""
        SELECT COUNT(DISTINCT cs.claim_id) FROM claim_sources cs
        JOIN claim_verdicts cv ON cv.claim_id = cs.claim_id
        WHERE cs.pipeline_slug = ? AND cv.verdict = 'refuted'
    """, (pipeline_slug,))
    refuted = (await cursor.fetchone())[0]

    cursor = await db.execute("""
        SELECT COUNT(DISTINCT cs.claim_id) FROM claim_sources cs
        JOIN claim_verdicts cv ON cv.claim_id = cs.claim_id
        WHERE cs.pipeline_slug = ? AND cv.verdict = 'supported'
    """, (pipeline_slug,))
    supported = (await cursor.fetchone())[0]

    return {
        "pipeline_slug": pipeline_slug,
        "total_claims": total,
        "supported": supported,
        "refuted": refuted,
        "pending": total - supported - refuted,
    }


async def get_jira_key_claims(db: aiosqlite.Connection, jira_key: str) -> list[dict]:
    cursor = await db.execute("""
        SELECT c.id, c.claim_text, c.claim_type
        FROM claims c
        JOIN claim_jira_keys jk ON jk.claim_id = c.id
        WHERE jk.jira_key = ?
        ORDER BY c.id
    """, (jira_key,))
    return [dict(r) for r in await cursor.fetchall()]
