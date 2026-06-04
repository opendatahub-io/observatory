import json

import aiosqlite


async def _resolve_pipeline_id(db: aiosqlite.Connection, slug: str) -> int | None:
    """Resolve a pipeline slug to its ID. Returns None if not found."""
    cursor = await db.execute("SELECT id FROM pipelines WHERE slug = ?", (slug,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return row["id"]


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

async def list_images(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_images WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_image(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    cursor = await db.execute(
        "INSERT INTO pipeline_images (pipeline_id, name, ref) VALUES (?, ?, ?)",
        (pipeline_id, data.get("name"), data["ref"]),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_images WHERE id = ?", (rid,))
    return dict(await cur2.fetchone())


async def delete_image(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_images WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

async def list_skills(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_skills WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_skill(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    cursor = await db.execute(
        "INSERT INTO pipeline_skills (pipeline_id, repo_url, branch, purpose) VALUES (?, ?, ?, ?)",
        (pipeline_id, data["repo_url"], data.get("branch"), data.get("purpose")),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_skills WHERE id = ?", (rid,))
    return dict(await cur2.fetchone())


async def delete_skill(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_skills WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Shared Libs
# ---------------------------------------------------------------------------

async def list_shared_libs(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_shared_libs WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_shared_lib(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    cursor = await db.execute(
        "INSERT INTO pipeline_shared_libs (pipeline_id, repo_url, purpose) VALUES (?, ?, ?)",
        (pipeline_id, data["repo_url"], data.get("purpose")),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_shared_libs WHERE id = ?", (rid,))
    return dict(await cur2.fetchone())


async def delete_shared_lib(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_shared_libs WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Jira Contracts
# ---------------------------------------------------------------------------

async def list_jira_contracts(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_jira_contracts WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["labels_applied"] = json.loads(d["labels_applied"]) if d["labels_applied"] else None
        result.append(d)
    return result


async def create_jira_contract(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    labels = data.get("labels_applied")
    labels_json = json.dumps(labels) if labels is not None else None
    cursor = await db.execute(
        "INSERT INTO pipeline_jira_contracts (pipeline_id, project, labels_applied) VALUES (?, ?, ?)",
        (pipeline_id, data["project"], labels_json),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_jira_contracts WHERE id = ?", (rid,))
    d = dict(await cur2.fetchone())
    d["labels_applied"] = json.loads(d["labels_applied"]) if d["labels_applied"] else None
    return d


async def delete_jira_contract(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_jira_contracts WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Telemetry Config
# ---------------------------------------------------------------------------

async def list_telemetry_config(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_telemetry_config WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_telemetry_config(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    cursor = await db.execute(
        "INSERT INTO pipeline_telemetry_config (pipeline_id, collector_type, endpoint, summary_script, status) VALUES (?, ?, ?, ?, ?)",
        (
            pipeline_id,
            data.get("collector_type"),
            data.get("endpoint"),
            data.get("summary_script"),
            data.get("status", "active"),
        ),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_telemetry_config WHERE id = ?", (rid,))
    return dict(await cur2.fetchone())


async def delete_telemetry_config(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_telemetry_config WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Artifact Config
# ---------------------------------------------------------------------------

async def list_artifact_config(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM pipeline_artifact_config WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def create_artifact_config(
    db: aiosqlite.Connection, pipeline_id: int, data: dict
) -> dict:
    cursor = await db.execute(
        "INSERT INTO pipeline_artifact_config (pipeline_id, results_repo, status) VALUES (?, ?, ?)",
        (pipeline_id, data.get("results_repo"), data.get("status", "active")),
    )
    await db.commit()
    rid = cursor.lastrowid
    cur2 = await db.execute("SELECT * FROM pipeline_artifact_config WHERE id = ?", (rid,))
    return dict(await cur2.fetchone())


async def delete_artifact_config(db: aiosqlite.Connection, resource_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM pipeline_artifact_config WHERE id = ?", (resource_id,)
    )
    await db.commit()
    return cursor.rowcount > 0
