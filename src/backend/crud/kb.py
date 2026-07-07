import json
import re
import uuid

import aiosqlite


def generate_slug(title: str) -> str:
    """Generate URL slug from title."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug


def _parse_tags(raw: str | None) -> list[str]:
    """Parse a JSON-encoded tags string, returning [] on failure."""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


async def list_categories(db: aiosqlite.Connection) -> list[dict]:
    """List all KB categories ordered by sort_order, name."""
    cursor = await db.execute(
        "SELECT * FROM kb_categories ORDER BY sort_order, name"
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_category(
    db: aiosqlite.Connection,
    name: str,
    description: str | None = None,
    sort_order: int = 0,
) -> dict:
    """Create a new category. Returns the created category dict."""
    cat_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO kb_categories (id, name, description, sort_order) VALUES (?, ?, ?, ?)",
        (cat_id, name, description, sort_order),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM kb_categories WHERE id = ?", (cat_id,)
    )
    return dict(await cursor.fetchone())


async def update_category(
    db: aiosqlite.Connection, category_id: str, **fields
) -> dict | None:
    """Update a category. Returns updated dict or None if not found.

    Accepts name, description, sort_order.
    """
    allowed = {"name", "description", "sort_order"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        cursor = await db.execute(
            "SELECT * FROM kb_categories WHERE id = ?", (category_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [category_id]
    await db.execute(
        f"UPDATE kb_categories SET {set_clause} WHERE id = ?",  # noqa: S608
        params,
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM kb_categories WHERE id = ?", (category_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_category(db: aiosqlite.Connection, category_id: str) -> bool:
    """Delete a category. Returns True if it existed."""
    cursor = await db.execute(
        "DELETE FROM kb_categories WHERE id = ?", (category_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def list_articles(
    db: aiosqlite.Connection,
    category_id: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List articles with optional filters.

    Returns {"articles": [...], "total": int}.
    Each article includes category_name from joined kb_categories.
    If search is provided, use simple LIKE matching (FTS is in search_articles).
    Parse tags from JSON string to list for each article.
    """
    where = []
    params: list = []

    if category_id:
        where.append("a.category_id = ?")
        params.append(category_id)
    if status:
        where.append("a.status = ?")
        params.append(status)
    if tag:
        where.append("a.tags LIKE ?")
        params.append(f'%"{tag}"%')
    if search:
        where.append("(a.title LIKE ? OR a.body LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"""
        SELECT COUNT(*) FROM kb_articles a
        WHERE {where_clause}
    """
    cursor = await db.execute(count_sql, params)
    total = (await cursor.fetchone())[0]

    query_sql = f"""
        SELECT a.*, c.name as category_name
        FROM kb_articles a
        LEFT JOIN kb_categories c ON c.id = a.category_id
        WHERE {where_clause}
        ORDER BY a.updated_at DESC
        LIMIT ? OFFSET ?
    """
    cursor = await db.execute(query_sql, params + [limit, offset])
    articles = [dict(r) for r in await cursor.fetchall()]

    for article in articles:
        article["tags"] = _parse_tags(article.get("tags"))

    return {"articles": articles, "total": total}


async def create_article(
    db: aiosqlite.Connection,
    title: str,
    body: str,
    category_id: str | None = None,
    tags: list[str] | None = None,
    status: str = "published",
    source: str = "manual",
    slug: str | None = None,
) -> dict:
    """Create a new article.

    Auto-generates slug from title if not provided.
    Tags stored as JSON array. After INSERT, sync to FTS5 index.
    Returns the created article dict with category_name.
    """
    article_id = str(uuid.uuid4())
    if not slug:
        slug = generate_slug(title)
    tags_json = json.dumps(tags or [])

    await db.execute(
        """INSERT INTO kb_articles (id, category_id, title, slug, body, tags, status, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (article_id, category_id, title, slug, body, tags_json, status, source),
    )

    # Sync to FTS5 index
    await db.execute(
        """INSERT INTO kb_articles_fts(rowid, title, body, tags)
        SELECT rowid, title, body, tags FROM kb_articles WHERE id = ?""",
        (article_id,),
    )
    await db.commit()

    cursor = await db.execute(
        """SELECT a.*, c.name as category_name
        FROM kb_articles a
        LEFT JOIN kb_categories c ON c.id = a.category_id
        WHERE a.id = ?""",
        (article_id,),
    )
    article = dict(await cursor.fetchone())
    article["tags"] = _parse_tags(article.get("tags"))
    return article


async def get_article(
    db: aiosqlite.Connection, id_or_slug: str
) -> dict | None:
    """Get article by id or slug. Try id first, then slug.

    Include category_name from join. Parse tags JSON.
    """
    cursor = await db.execute(
        """SELECT a.*, c.name as category_name
        FROM kb_articles a
        LEFT JOIN kb_categories c ON c.id = a.category_id
        WHERE a.id = ?""",
        (id_or_slug,),
    )
    row = await cursor.fetchone()

    if not row:
        cursor = await db.execute(
            """SELECT a.*, c.name as category_name
            FROM kb_articles a
            LEFT JOIN kb_categories c ON c.id = a.category_id
            WHERE a.slug = ?""",
            (id_or_slug,),
        )
        row = await cursor.fetchone()

    if not row:
        return None

    article = dict(row)
    article["tags"] = _parse_tags(article.get("tags"))
    return article


async def update_article(
    db: aiosqlite.Connection, article_id: str, **fields
) -> dict | None:
    """Update an article.

    Accepts title, body, category_id, tags, status, slug.
    If tags provided as list, serialize to JSON. Update updated_at.
    Re-sync FTS5 after update. Returns updated article dict or None.
    """
    allowed = {"title", "body", "category_id", "tags", "status", "slug"}
    updates = {k: v for k, v in fields.items() if k in allowed}

    # Check article exists
    cursor = await db.execute(
        "SELECT id FROM kb_articles WHERE id = ?", (article_id,)
    )
    if not await cursor.fetchone():
        return None

    if "tags" in updates and isinstance(updates["tags"], list):
        updates["tags"] = json.dumps(updates["tags"])

    updates["updated_at"] = "datetime('now')"

    set_parts = []
    params: list = []
    for k, v in updates.items():
        if k == "updated_at":
            set_parts.append("updated_at = datetime('now')")
        else:
            set_parts.append(f"{k} = ?")
            params.append(v)

    params.append(article_id)
    await db.execute(
        f"UPDATE kb_articles SET {', '.join(set_parts)} WHERE id = ?",  # noqa: S608
        params,
    )

    # Re-sync FTS5: delete old entry, insert new
    await db.execute(
        """DELETE FROM kb_articles_fts
        WHERE rowid = (SELECT rowid FROM kb_articles WHERE id = ?)""",
        (article_id,),
    )
    await db.execute(
        """INSERT INTO kb_articles_fts(rowid, title, body, tags)
        SELECT rowid, title, body, tags FROM kb_articles WHERE id = ?""",
        (article_id,),
    )
    await db.commit()

    cursor = await db.execute(
        """SELECT a.*, c.name as category_name
        FROM kb_articles a
        LEFT JOIN kb_categories c ON c.id = a.category_id
        WHERE a.id = ?""",
        (article_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    article = dict(row)
    article["tags"] = _parse_tags(article.get("tags"))
    return article


async def delete_article(db: aiosqlite.Connection, article_id: str) -> bool:
    """Delete an article. Remove FTS entry first, then delete.

    Returns True if it existed.
    """
    # Remove FTS entry before deleting the article row
    await db.execute(
        """DELETE FROM kb_articles_fts
        WHERE rowid = (SELECT rowid FROM kb_articles WHERE id = ?)""",
        (article_id,),
    )
    cursor = await db.execute(
        "DELETE FROM kb_articles WHERE id = ?", (article_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def search_articles(
    db: aiosqlite.Connection, query: str, limit: int = 20
) -> list[dict]:
    """Full-text search via FTS5 MATCH.

    Join with kb_articles and kb_categories for full data.
    Parse tags JSON. Return list of article dicts ordered by rank.
    """
    cursor = await db.execute(
        """SELECT a.*, c.name as category_name, fts.rank
        FROM kb_articles_fts fts
        JOIN kb_articles a ON a.rowid = fts.rowid
        LEFT JOIN kb_categories c ON c.id = a.category_id
        WHERE kb_articles_fts MATCH ?
        ORDER BY fts.rank
        LIMIT ?""",
        (query, limit),
    )
    articles = [dict(r) for r in await cursor.fetchall()]

    for article in articles:
        article["tags"] = _parse_tags(article.get("tags"))
        article.pop("rank", None)

    return articles
