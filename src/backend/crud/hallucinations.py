import hashlib
import json
import re

import aiosqlite

JIRA_KEY_PATTERN = re.compile(r"\b(RHAISTRAT|RHAIRFE|RHOAIENG|AIPCC|INFERENG|RHAIENG)-\d+\b")


def _claim_hash(text: str) -> str:
    """Compute claim hash matching ingest-claims.py normalization."""
    normalized = " ".join(text.lower().split())
    normalized = normalized.rstrip(".,;:!?")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _extract_jira_keys(text: str) -> list[str]:
    return [m.group(0) for m in JIRA_KEY_PATTERN.finditer(text)]


async def ingest_claims(
    db: aiosqlite.Connection,
    source_file: str,
    pipeline_slug: str,
    claims: list[dict],
) -> dict:
    """Ingest a batch of claims, deduplicating by content hash.

    Mirrors the logic in scripts/ingest-claims.py.
    """
    total = 0
    new = 0
    total_sources = 0
    total_jira_links = 0

    for claim_data in claims:
        claim_text = claim_data.get("claim", "").strip()
        if not claim_text:
            continue

        total += 1
        chash = _claim_hash(claim_text)
        claim_type = claim_data.get("type")
        original_text = claim_data.get("original_text")

        cursor = await db.execute(
            "SELECT id FROM claims WHERE claim_hash = ?", (chash,)
        )
        existing = await cursor.fetchone()

        if existing:
            claim_id = existing["id"]
        else:
            cursor = await db.execute(
                "INSERT INTO claims (claim_text, claim_type, claim_hash) VALUES (?, ?, ?)",
                (claim_text, claim_type, chash),
            )
            claim_id = cursor.lastrowid
            new += 1

        exists = await db.execute(
            "SELECT id FROM claim_sources WHERE claim_id = ? AND source_file = ?",
            (claim_id, source_file),
        )
        if not await exists.fetchone():
            await db.execute(
                "INSERT INTO claim_sources (claim_id, pipeline_slug, source_file, original_text) VALUES (?, ?, ?, ?)",
                (claim_id, pipeline_slug, source_file, original_text),
            )
            total_sources += 1

        jira_keys = set(_extract_jira_keys(claim_text))
        if original_text:
            jira_keys.update(_extract_jira_keys(original_text))
        jira_keys.update(_extract_jira_keys(source_file))

        for jk in jira_keys:
            exists = await db.execute(
                "SELECT id FROM claim_jira_keys WHERE claim_id = ? AND jira_key = ?",
                (claim_id, jk),
            )
            if not await exists.fetchone():
                await db.execute(
                    "INSERT INTO claim_jira_keys (claim_id, jira_key) VALUES (?, ?)",
                    (claim_id, jk),
                )
                total_jira_links += 1

    await db.commit()

    return {
        "ingested": total,
        "new": new,
        "duplicate": total - new,
        "jira_links": total_jira_links,
        "sources_added": total_sources,
    }


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

    cursor = await db.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_verdicts WHERE verdict = 'insufficient'")
    insufficient = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT jira_key) FROM claim_jira_keys")
    jira_keys = (await cursor.fetchone())[0]

    return {
        "total_claims": total,
        "verified": verified,
        "pending": total - verified,
        "supported": supported,
        "refuted": refuted,
        "inconclusive": inconclusive,
        "insufficient": insufficient,
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
    source: str | None = None,
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
    if source:
        where.append("cs.source_file LIKE ?")
        params.append(f"%{source}%")
    if search:
        if search.isdigit():
            where.append("c.id = ?")
            params.append(int(search))
        else:
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
            COALESCE((SELECT confidence FROM claim_verdicts WHERE claim_id = c.id ORDER BY verified_at DESC LIMIT 1), -1) as confidence_val,
            (SELECT category FROM claim_explanations WHERE claim_id = c.id ORDER BY explained_at DESC LIMIT 1) as explanation_category
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
        "SELECT * FROM claim_verdicts WHERE claim_id = ?",
        (claim_id,),
    )
    verdict_row = await cursor.fetchone()
    claim["verdict"] = dict(verdict_row) if verdict_row else None

    cursor = await db.execute(
        "SELECT id, category, explanation, sources_used, explained_at FROM claim_explanations WHERE claim_id = ?",
        (claim_id,),
    )
    exp_row = await cursor.fetchone()
    if exp_row:
        explanation = dict(exp_row)
        if explanation.get("sources_used"):
            try:
                explanation["sources_used"] = json.loads(explanation["sources_used"])
            except (json.JSONDecodeError, TypeError):
                explanation["sources_used"] = []
        claim["explanation"] = explanation
    else:
        claim["explanation"] = None

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


async def get_issues_by_verdicts(
    db: aiosqlite.Connection,
    sort: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Aggregate claims by Jira issue, sorted by verdict counts."""
    count_cursor = await db.execute(
        "SELECT COUNT(DISTINCT jira_key) FROM claim_jira_keys"
    )
    total = (await count_cursor.fetchone())[0]

    sort_map = {
        "jira_key": "jk.jira_key",
        "total": "total_claims",
        "supported": "supported",
        "refuted": "refuted",
        "insufficient": "insufficient",
        "inconclusive": "inconclusive",
        "pending": "pending",
    }
    order_col = sort_map.get(sort or "", "refuted")
    order_dir = "DESC" if sort_dir != "asc" else "ASC"

    cursor = await db.execute(f"""
        SELECT
            jk.jira_key,
            COUNT(DISTINCT jk.claim_id) as total_claims,
            COUNT(DISTINCT CASE WHEN cv.verdict = 'supported' THEN jk.claim_id END) as supported,
            COUNT(DISTINCT CASE WHEN cv.verdict = 'refuted' THEN jk.claim_id END) as refuted,
            COUNT(DISTINCT CASE WHEN cv.verdict = 'insufficient' THEN jk.claim_id END) as insufficient,
            COUNT(DISTINCT CASE WHEN cv.verdict = 'inconclusive' THEN jk.claim_id END) as inconclusive,
            COUNT(DISTINCT CASE WHEN cv.claim_id IS NULL THEN jk.claim_id END) as pending
        FROM claim_jira_keys jk
        LEFT JOIN claim_verdicts cv ON cv.claim_id = jk.claim_id
        GROUP BY jk.jira_key
        ORDER BY {order_col} {order_dir}
        LIMIT ? OFFSET ?
    """, (limit, offset))

    issues = [dict(r) for r in await cursor.fetchall()]
    return {"issues": issues, "total": total}


async def store_verdicts(
    db: aiosqlite.Connection,
    verdicts: list[dict],
) -> dict:
    """Store verification verdicts for claims.

    Each verdict dict must have claim_id, verdict, confidence.
    Optional: evidence_summary, evidence_source, evidence_detail.
    """
    stored = 0
    skipped = 0

    for v in verdicts:
        claim_id = v.get("claim_id")
        if not claim_id:
            skipped += 1
            continue

        cursor = await db.execute("SELECT id FROM claims WHERE id = ?", (claim_id,))
        if not await cursor.fetchone():
            skipped += 1
            continue

        existing = await db.execute(
            "SELECT id FROM claim_verdicts WHERE claim_id = ?", (claim_id,)
        )
        if await existing.fetchone():
            await db.execute(
                """UPDATE claim_verdicts
                    SET verdict = ?, confidence = ?, evidence_summary = ?,
                        evidence_source = ?, evidence_detail = ?, verified_at = CURRENT_TIMESTAMP
                    WHERE claim_id = ?""",
                (
                    v.get("verdict", "inconclusive"),
                    v.get("confidence", 0),
                    v.get("evidence_summary"),
                    v.get("evidence_source"),
                    v.get("evidence_detail"),
                    claim_id,
                ),
            )
        else:
            await db.execute(
                """INSERT INTO claim_verdicts
                    (claim_id, verdict, confidence, evidence_summary, evidence_source, evidence_detail)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    claim_id,
                    v.get("verdict", "inconclusive"),
                    v.get("confidence", 0),
                    v.get("evidence_summary"),
                    v.get("evidence_source"),
                    v.get("evidence_detail"),
                ),
            )
        stored += 1

    await db.commit()
    return {"stored": stored, "skipped": skipped}


async def get_jira_key_claims(db: aiosqlite.Connection, jira_key: str) -> list[dict]:
    cursor = await db.execute("""
        SELECT c.id, c.claim_text, c.claim_type
        FROM claims c
        JOIN claim_jira_keys jk ON jk.claim_id = c.id
        WHERE jk.jira_key = ?
        ORDER BY c.id
    """, (jira_key,))
    return [dict(r) for r in await cursor.fetchall()]


async def store_explanations(
    db: aiosqlite.Connection,
    explanations: list[dict],
) -> dict:
    """Store root-cause explanations for claims."""
    stored = 0
    skipped = 0

    for e in explanations:
        claim_id = e.get("claim_id")
        if not claim_id:
            skipped += 1
            continue

        cursor = await db.execute("SELECT id FROM claims WHERE id = ?", (claim_id,))
        if not await cursor.fetchone():
            skipped += 1
            continue

        sources_json = json.dumps(e.get("sources_used", []))

        existing = await db.execute(
            "SELECT id FROM claim_explanations WHERE claim_id = ?", (claim_id,)
        )
        if await existing.fetchone():
            await db.execute(
                """UPDATE claim_explanations
                    SET category = ?, explanation = ?, sources_used = ?, explained_at = CURRENT_TIMESTAMP
                    WHERE claim_id = ?""",
                (e.get("category", "unknown"), e.get("explanation", ""), sources_json, claim_id),
            )
        else:
            await db.execute(
                """INSERT INTO claim_explanations
                    (claim_id, category, explanation, sources_used)
                VALUES (?, ?, ?, ?)""",
                (claim_id, e.get("category", "unknown"), e.get("explanation", ""), sources_json),
            )
        stored += 1

    await db.commit()
    return {"stored": stored, "skipped": skipped}


async def get_explanations(
    db: aiosqlite.Connection,
    category: str | None = None,
    jira_key: str | None = None,
    search: str | None = None,
    sort: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List explanations with filters."""
    where = []
    params: list = []

    if category:
        where.append("ce.category = ?")
        params.append(category)
    if jira_key:
        where.append("c.id IN (SELECT claim_id FROM claim_jira_keys WHERE jira_key = ?)")
        params.append(jira_key)
    if search:
        where.append("(ce.explanation LIKE ? OR c.claim_text LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"""
        SELECT COUNT(DISTINCT ce.id) FROM claim_explanations ce
        JOIN claims c ON c.id = ce.claim_id
        WHERE {where_clause}
    """
    cursor = await db.execute(count_sql, params)
    total = (await cursor.fetchone())[0]

    sort_map = {
        "category": "ce.category",
        "claim": "c.claim_text",
        "date": "ce.explained_at",
    }
    order_col = sort_map.get(sort or "", "ce.id")
    order_dir = "DESC" if sort_dir != "asc" else "ASC"
    if order_col == "ce.id":
        order_dir = "DESC"

    query_sql = f"""
        SELECT ce.id, ce.claim_id, ce.category, ce.explanation, ce.sources_used, ce.explained_at,
            c.claim_text, c.claim_type,
            (SELECT verdict FROM claim_verdicts WHERE claim_id = c.id ORDER BY verified_at DESC LIMIT 1) as verdict,
            (SELECT confidence FROM claim_verdicts WHERE claim_id = c.id ORDER BY verified_at DESC LIMIT 1) as confidence
        FROM claim_explanations ce
        JOIN claims c ON c.id = ce.claim_id
        WHERE {where_clause}
        ORDER BY {order_col} {order_dir}
        LIMIT ? OFFSET ?
    """
    cursor = await db.execute(query_sql, params + [limit, offset])
    rows = [dict(r) for r in await cursor.fetchall()]

    for row in rows:
        if row.get("sources_used"):
            try:
                row["sources_used"] = json.loads(row["sources_used"])
            except (json.JSONDecodeError, TypeError):
                row["sources_used"] = []

        cid = row["claim_id"]
        cursor = await db.execute("SELECT jira_key FROM claim_jira_keys WHERE claim_id = ?", (cid,))
        row["jira_keys"] = [r["jira_key"] for r in await cursor.fetchall()]

    return {"explanations": rows, "total": total}


async def get_explanation_categories(db: aiosqlite.Connection) -> list[dict]:
    """Get category distribution for explanations."""
    cursor = await db.execute(
        "SELECT category, COUNT(*) as count FROM claim_explanations GROUP BY category ORDER BY count DESC"
    )
    return [dict(r) for r in await cursor.fetchall()]


async def clear_all_claims(db: aiosqlite.Connection) -> dict:
    """Delete all claims data (claims, sources, verdicts, explanations, jira keys)."""
    tables = ["claim_explanations", "claim_verdicts", "claim_jira_keys", "claim_sources", "claims"]
    counts = {}
    for table in tables:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        counts[table] = (await cursor.fetchone())[0]
        await db.execute(f"DELETE FROM {table}")  # noqa: S608
    await db.commit()
    return counts
