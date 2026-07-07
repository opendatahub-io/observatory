from __future__ import annotations

import json
import uuid

import aiosqlite


def _parse_config(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["config"] = _parse_config(d.get("config"))
    return d


async def list_data_sources(
    db: aiosqlite.Connection,
    status: str | None = None,
    source_type: str | None = None,
) -> list[dict]:
    where = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if source_type:
        where.append("source_type = ?")
        params.append(source_type)
    where_clause = " AND ".join(where) if where else "1=1"
    cursor = await db.execute(
        f"SELECT * FROM data_sources WHERE {where_clause} ORDER BY name",
        params,
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_data_source(
    db: aiosqlite.Connection, source_id: str
) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM data_sources WHERE id = ?", (source_id,)
    )
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def create_data_source(
    db: aiosqlite.Connection,
    name: str,
    source_type: str,
    endpoint: str | None = None,
    description: str | None = None,
    config: dict | None = None,
    status: str = "active",
) -> dict:
    source_id = str(uuid.uuid4())
    config_json = json.dumps(config or {})
    await db.execute(
        """INSERT INTO data_sources (id, name, source_type, endpoint, description, config, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_id, name, source_type, endpoint, description, config_json, status),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM data_sources WHERE id = ?", (source_id,)
    )
    return _row_to_dict(await cursor.fetchone())


async def update_data_source(
    db: aiosqlite.Connection, source_id: str, **fields
) -> dict | None:
    allowed = {"name", "source_type", "endpoint", "description", "config", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}

    cursor = await db.execute(
        "SELECT id FROM data_sources WHERE id = ?", (source_id,)
    )
    if not await cursor.fetchone():
        return None

    if "config" in updates and isinstance(updates["config"], dict):
        updates["config"] = json.dumps(updates["config"])

    set_parts = ["updated_at = datetime('now')"]
    params: list = []
    for k, v in updates.items():
        set_parts.append(f"{k} = ?")
        params.append(v)

    params.append(source_id)
    await db.execute(
        f"UPDATE data_sources SET {', '.join(set_parts)} WHERE id = ?",
        params,
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM data_sources WHERE id = ?", (source_id,)
    )
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def delete_data_source(db: aiosqlite.Connection, source_id: str) -> bool:
    cursor = await db.execute(
        "DELETE FROM data_sources WHERE id = ?", (source_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_active_sources_summary(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT name, source_type, endpoint, description FROM data_sources WHERE status = 'active' ORDER BY name LIMIT 50"
    )
    return [dict(r) for r in await cursor.fetchall()]
