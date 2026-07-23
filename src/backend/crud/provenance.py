import aiosqlite


async def get_run_commands(db: aiosqlite.Connection, run_id: int) -> list[dict]:
    """Return all commands for a pipeline run, ordered by step_order."""
    cursor = await db.execute(
        "SELECT * FROM run_commands WHERE pipeline_run_id = ? ORDER BY step_order",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_run_packages(
    db: aiosqlite.Connection, run_id: int, manager: str | None = None
) -> list[dict]:
    """Return packages for a pipeline run, optionally filtered by manager.

    Queries both run_packages (artifact-parsed) and trace_packages (job-trace-parsed).
    """
    mgr_filter = "AND manager = ?" if manager else ""
    params: list = [run_id]
    if manager:
        params.append(manager)

    cursor = await db.execute(f"""
        SELECT id, pipeline_run_id, name, version, manager FROM run_packages
        WHERE pipeline_run_id = ? {mgr_filter}
        UNION ALL
        SELECT id, pipeline_run_id, name, version, manager FROM trace_packages
        WHERE pipeline_run_id = ? {mgr_filter}
        ORDER BY name
    """, params + params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_run_containers(db: aiosqlite.Connection, run_id: int) -> list[dict]:
    """Return all containers for a pipeline run."""
    cursor = await db.execute(
        "SELECT * FROM run_containers WHERE pipeline_run_id = ? ORDER BY image_ref",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_run_provenance(db: aiosqlite.Connection, run_id: int) -> dict:
    """Return full provenance (commands, packages, containers) for a run."""
    commands = await get_run_commands(db, run_id)
    packages = await get_run_packages(db, run_id)
    containers = await get_run_containers(db, run_id)
    return {
        "run_id": run_id,
        "commands": commands,
        "packages": packages,
        "containers": containers,
    }


async def get_package_inventory(db: aiosqlite.Connection) -> list[dict]:
    """Cross-pipeline package inventory: all packages with which pipelines use them."""
    cursor = await db.execute(
        """
        SELECT manager, name, version, slug FROM (
            SELECT rp.manager, rp.name, rp.version, p.slug
            FROM run_packages rp
            JOIN pipeline_runs pr ON rp.pipeline_run_id = pr.id
            JOIN pipelines p ON pr.pipeline_id = p.id
            UNION ALL
            SELECT tp.manager, tp.name, tp.version, p.slug
            FROM trace_packages tp
            JOIN pipeline_runs pr ON tp.pipeline_run_id = pr.id
            JOIN pipelines p ON pr.pipeline_id = p.id
        )
        ORDER BY manager, name
        """
    )
    rows = await cursor.fetchall()

    # Group by (manager, name)
    inventory: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["manager"], row["name"])
        if key not in inventory:
            inventory[key] = {
                "manager": row["manager"],
                "name": row["name"],
                "versions": set(),
                "pipelines": set(),
            }
        inventory[key]["versions"].add(row["version"])
        inventory[key]["pipelines"].add(row["slug"])

    # Convert sets to sorted lists
    result = []
    for item in inventory.values():
        result.append({
            "manager": item["manager"],
            "name": item["name"],
            "versions": sorted(item["versions"]),
            "pipelines": sorted(item["pipelines"]),
        })
    return result


async def get_container_inventory(db: aiosqlite.Connection) -> list[dict]:
    """Cross-pipeline container inventory: all images with which pipelines use them."""
    cursor = await db.execute(
        """
        SELECT image_ref, image_digest, slug FROM (
            SELECT rc.image_ref, rc.image_digest, p.slug
            FROM run_containers rc
            JOIN pipeline_runs pr ON rc.pipeline_run_id = pr.id
            JOIN pipelines p ON pr.pipeline_id = p.id
            UNION ALL
            SELECT tm_img.value AS image_ref, tm_dig.value AS image_digest, p.slug
            FROM trace_metadata tm_img
            JOIN pipeline_runs pr ON tm_img.pipeline_run_id = pr.id
            JOIN pipelines p ON pr.pipeline_id = p.id
            LEFT JOIN trace_metadata tm_dig
                ON tm_dig.pipeline_run_id = tm_img.pipeline_run_id AND tm_dig.key = 'container_digest'
            WHERE tm_img.key = 'container_image'
        )
        ORDER BY image_ref
        """
    )
    rows = await cursor.fetchall()

    inventory: dict[str, dict] = {}
    for row in rows:
        key = row["image_ref"]
        if key not in inventory:
            inventory[key] = {
                "image_ref": row["image_ref"],
                "digests": set(),
                "pipelines": set(),
            }
        if row["image_digest"]:
            inventory[key]["digests"].add(row["image_digest"])
        inventory[key]["pipelines"].add(row["slug"])

    result = []
    for item in inventory.values():
        result.append({
            "image_ref": item["image_ref"],
            "digests": sorted(item["digests"]),
            "pipelines": sorted(item["pipelines"]),
        })
    return result
