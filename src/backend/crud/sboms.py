import json
from typing import Optional

import aiosqlite


async def upsert_sbom(db: aiosqlite.Connection, data: dict) -> dict:
    """Insert or update an SBOM by image_digest. Return the row."""
    sbom_json = json.dumps(data["sbom"])

    # Try to find existing
    cursor = await db.execute(
        "SELECT id FROM container_sboms WHERE image_digest = ?",
        (data["image_digest"],),
    )
    existing = await cursor.fetchone()

    if existing is not None:
        await db.execute(
            """
            UPDATE container_sboms
            SET image_ref = ?, format = ?, sbom = ?, generator = ?,
                generated_at = ?
            WHERE image_digest = ?
            """,
            (
                data["image_ref"],
                data.get("format", "spdx-json"),
                sbom_json,
                data.get("generator"),
                data.get("generated_at"),
                data["image_digest"],
            ),
        )
    else:
        await db.execute(
            """
            INSERT INTO container_sboms
                (image_digest, image_ref, format, sbom, generator, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["image_digest"],
                data["image_ref"],
                data.get("format", "spdx-json"),
                sbom_json,
                data.get("generator"),
                data.get("generated_at"),
            ),
        )

    await db.commit()
    return await get_sbom_by_digest(db, data["image_digest"])


async def list_sboms(db: aiosqlite.Connection) -> list[dict]:
    """Return all SBOMs without the full sbom document."""
    cursor = await db.execute(
        """
        SELECT id, image_digest, image_ref, format, generator,
               generated_at, created_at
        FROM container_sboms
        ORDER BY id
        """
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_sbom_by_digest(
    db: aiosqlite.Connection, digest: str
) -> Optional[dict]:
    """Return the full SBOM row for a given digest, parsing the JSON."""
    cursor = await db.execute(
        "SELECT * FROM container_sboms WHERE image_digest = ?",
        (digest,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)
    result["sbom"] = json.loads(result["sbom"])
    return result


async def get_vulnerabilities_for_digest(
    db: aiosqlite.Connection, digest: str
) -> list[dict]:
    """Return vulnerabilities for a container SBOM identified by digest."""
    cursor = await db.execute(
        """
        SELECT sv.*
        FROM sbom_vulnerabilities sv
        JOIN container_sboms cs ON sv.sbom_id = cs.id
        WHERE cs.image_digest = ?
        ORDER BY sv.id
        """,
        (digest,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_vulnerability_summary(
    db: aiosqlite.Connection, severity: Optional[str] = None
) -> list[dict]:
    """Cross-pipeline vulnerability summary, optionally filtered by severity."""
    conditions: list[str] = []
    params: list = []

    if severity is not None:
        conditions.append("LOWER(sv.severity) = LOWER(?)")
        params.append(severity)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            sv.vuln_id,
            sv.package_name,
            sv.installed_version,
            sv.fixed_version,
            sv.severity,
            cs.image_digest,
            cs.image_ref,
            sv.scanned_at
        FROM sbom_vulnerabilities sv
        JOIN container_sboms cs ON sv.sbom_id = cs.id
        {where}
        ORDER BY sv.severity, sv.vuln_id
    """

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
