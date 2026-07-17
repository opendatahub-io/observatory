import json
import re
import time
from collections.abc import Iterable

import aiosqlite

from backend.metrics import (
    claim_candidate_generation_duration_seconds,
    claim_candidate_generation_failures_total,
    claim_candidate_shortlist_size,
)
from backend.schemas.claim_consolidation import (
    CandidateGenerationInput,
    CanonicalGroupInput,
    ConsolidationEvaluationInput,
    ConsolidationPolicyInput,
    EquivalenceDecisionInput,
    GroupSplitInput,
    ModelShadowDecisionInput,
)


TOKEN_PATTERN = re.compile(r"[^\W_]{2,}", re.UNICODE)
STOP_WORDS = {
    "and", "are", "for", "from", "has", "have", "into", "not", "that",
    "the", "their", "this", "was", "were", "will", "with",
}


class ConsolidationConflict(Exception):
    pass


def _row(row: aiosqlite.Row | None) -> dict | None:
    return dict(row) if row else None


def _json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _fts_query(text: str) -> str | None:
    tokens = []
    for token in TOKEN_PATTERN.findall(text.casefold()):
        if token not in STOP_WORDS and token not in tokens:
            tokens.append(token)
    return " OR ".join(f'"{token}"' for token in tokens[:24]) or None


async def _claim_qualifiers(db: aiosqlite.Connection, claim_id: int) -> dict:
    cursor = await db.execute(
        """SELECT claim_type, modality, product_version, temporal_scope, clarification
           FROM claim_occurrences WHERE normalized_claim_id = ? ORDER BY id""",
        (claim_id,),
    )
    rows = await cursor.fetchall()
    fields = ("claim_type", "modality", "product_version", "temporal_scope", "clarification")
    return {
        field: sorted({row[field].strip() for row in rows if row[field] and row[field].strip()})
        for field in fields
    }


async def generate_candidates(
    db: aiosqlite.Connection, data: CandidateGenerationInput
) -> dict:
    started = time.monotonic()
    existing = await (await db.execute(
        "SELECT * FROM claim_consolidation_receipts WHERE run_key = ?", (data.run_key,)
    )).fetchone()
    if existing:
        if existing["retrieval_revision"] != data.retrieval_revision:
            raise ConsolidationConflict("run_key already uses another retrieval revision")
        if existing["status"] == "complete":
            return {"receipt": dict(existing), "created": 0, "replayed": True}
        cursor_claim_id = existing["cursor_claim_id"] or 0
        receipt_id = existing["id"]
    else:
        cursor = await db.execute(
            """INSERT INTO claim_consolidation_receipts
               (run_key, mode, retrieval_revision, status)
               VALUES (?, 'candidate_generation', ?, 'running')""",
            (data.run_key, data.retrieval_revision),
        )
        receipt_id = cursor.lastrowid
        cursor_claim_id = 0

    created = 0
    processed = 0
    shortlist_sizes: list[int] = []
    try:
        params: list = [cursor_claim_id]
        where = "id > ?"
        if data.claim_id is not None:
            where += " AND id = ?"
            params.append(data.claim_id)
        params.append(data.batch_size)
        claims = await (await db.execute(
            f"SELECT id, claim_text FROM claims WHERE {where} ORDER BY id LIMIT ?", params
        )).fetchall()
        for claim in claims:
            query = _fts_query(claim["claim_text"])
            if query is None:
                cursor_claim_id = claim["id"]
                continue
            matches = await (await db.execute(
                """SELECT c.id, bm25(claims_fts) AS rank
                   FROM claims_fts JOIN claims c ON c.id = claims_fts.rowid
                   WHERE claims_fts MATCH ? AND c.id != ?
                   ORDER BY rank LIMIT ?""",
                (query, claim["id"], data.shortlist_size),
            )).fetchall()
            shortlist_sizes.append(len(matches))
            for match in matches:
                left, right = sorted((claim["id"], match["id"]))
                result = await db.execute(
                    """INSERT OR IGNORE INTO claim_similarity_candidates
                       (left_normalized_claim_id, right_normalized_claim_id,
                        retrieval_method, retrieval_score, retrieval_query,
                        retrieval_revision)
                       VALUES (?, ?, 'sqlite_fts5_bm25', ?, ?, ?)""",
                    (left, right, 1 / (1 + abs(match["rank"])), query,
                     data.retrieval_revision),
                )
                created += result.rowcount
            processed += 1
            cursor_claim_id = claim["id"]
            await db.execute(
                "UPDATE claim_consolidation_receipts SET cursor_claim_id = ? WHERE id = ?",
                (cursor_claim_id, receipt_id),
            )
        complete = data.claim_id is not None or len(claims) < data.batch_size
        metrics = {
            "processed_claims": processed,
            "created_candidates": created,
            "mean_shortlist_size": (
                sum(shortlist_sizes) / len(shortlist_sizes) if shortlist_sizes else 0
            ),
        }
        await db.execute(
            """UPDATE claim_consolidation_receipts
               SET status = ?, metrics = ?, completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP END
               WHERE id = ?""",
            ("complete" if complete else "running", json.dumps(metrics, sort_keys=True),
             complete, receipt_id),
        )
        await db.commit()
        claim_candidate_shortlist_size.observe(metrics["mean_shortlist_size"])
        receipt = await (await db.execute(
            "SELECT * FROM claim_consolidation_receipts WHERE id = ?", (receipt_id,)
        )).fetchone()
        return {"receipt": dict(receipt), "created": created, "replayed": False}
    except Exception:
        claim_candidate_generation_failures_total.inc()
        await db.execute(
            "UPDATE claim_consolidation_receipts SET status = 'failed' WHERE id = ?",
            (receipt_id,),
        )
        await db.commit()
        raise
    finally:
        claim_candidate_generation_duration_seconds.observe(time.monotonic() - started)


def _incompatible(left: dict, right: dict) -> tuple[bool, str]:
    for field in ("product_version", "temporal_scope"):
        left_values = set(left[field])
        right_values = set(right[field])
        if left_values and right_values and left_values.isdisjoint(right_values):
            return True, f"explicit {field} values are incompatible"
    fact_markers = {"fact", "current", "actual"}
    proposal_markers = {"proposal", "proposed", "requirement", "required", "future"}
    left_modality = {value.casefold() for value in left["modality"]}
    right_modality = {value.casefold() for value in right["modality"]}
    if ((left_modality & fact_markers and right_modality & proposal_markers)
            or (right_modality & fact_markers and left_modality & proposal_markers)):
        return True, "fact and proposal/requirement modalities are incompatible"
    return False, ""


async def run_shadow_decisions(
    db: aiosqlite.Connection, decision_revision: str, limit: int
) -> dict:
    candidates = await (await db.execute(
        """SELECT c.* FROM claim_similarity_candidates c
           WHERE NOT EXISTS (
             SELECT 1 FROM claim_equivalence_decisions d
             WHERE d.candidate_id = c.id AND d.decider_type = 'deterministic'
               AND d.decider_revision = ?)
           ORDER BY c.id LIMIT ?""",
        (decision_revision, limit),
    )).fetchall()
    counts = {key: 0 for key in ("equivalent", "related", "distinct", "needs_review")}
    for candidate in candidates:
        left = await _claim_qualifiers(db, candidate["left_normalized_claim_id"])
        right = await _claim_qualifiers(db, candidate["right_normalized_claim_id"])
        incompatible, rationale = _incompatible(left, right)
        decision = "distinct" if incompatible else "needs_review"
        if not incompatible:
            rationale = "lexical similarity cannot establish mutual entailment safely"
        await db.execute(
            """INSERT INTO claim_equivalence_decisions
               (candidate_id, decision, rationale, compared_qualifiers,
                decider_type, decider_revision, confidence)
               VALUES (?, ?, ?, ?, 'deterministic', ?, ?)""",
            (candidate["id"], decision, rationale,
             json.dumps({"left": left, "right": right}, sort_keys=True),
             decision_revision, 1.0 if incompatible else 0.0),
        )
        await db.execute(
            "UPDATE claim_similarity_candidates SET status = 'decided' WHERE id = ?",
            (candidate["id"],),
        )
        counts[decision] += 1
    await db.commit()
    return {"processed": len(candidates), "counts": counts}


async def _active_group_id(db: aiosqlite.Connection, claim_id: int) -> int | None:
    row = await (await db.execute(
        """SELECT canonical_group_id FROM claim_canonical_memberships
           WHERE normalized_claim_id = ? AND retired_at IS NULL""",
        (claim_id,),
    )).fetchone()
    return row["canonical_group_id"] if row else None


async def _group_join_conflict(
    db: aiosqlite.Connection, group_id: int, claim_id: int
) -> str | None:
    claim_qualifiers = await _claim_qualifiers(db, claim_id)
    members = await (await db.execute(
        """SELECT normalized_claim_id FROM claim_canonical_memberships
           WHERE canonical_group_id = ? AND retired_at IS NULL""",
        (group_id,),
    )).fetchall()
    for member in members:
        member_id = member["normalized_claim_id"]
        incompatible, rationale = _incompatible(
            await _claim_qualifiers(db, member_id), claim_qualifiers
        )
        if incompatible:
            return f"claim {member_id} has {rationale}"
        left, right = sorted((member_id, claim_id))
        conflict = await (await db.execute(
            """SELECT decision.decision FROM claim_similarity_candidates candidate
               JOIN claim_equivalence_decisions decision ON decision.id = (
                 SELECT id FROM claim_equivalence_decisions current
                 WHERE current.candidate_id = candidate.id
                 ORDER BY current.created_at DESC, current.id DESC LIMIT 1)
               WHERE candidate.left_normalized_claim_id = ?
                 AND candidate.right_normalized_claim_id = ?
                 AND decision.decision IN ('related', 'distinct') LIMIT 1""",
            (left, right),
        )).fetchone()
        if conflict:
            return f"claim {member_id} has a latest {conflict['decision']} decision"
    return None


async def _append_memberships(
    db: aiosqlite.Connection, group_id: int, claim_ids: Iterable[int],
    decision_id: int | None, actor: str,
) -> None:
    for claim_id in claim_ids:
        active = await _active_group_id(db, claim_id)
        if active is not None:
            if active == group_id:
                continue
            raise ConsolidationConflict(f"claim {claim_id} already belongs to group {active}")
        await db.execute(
            """INSERT INTO claim_canonical_memberships
               (canonical_group_id, normalized_claim_id, decision_id, actor)
               VALUES (?, ?, ?, ?)""",
            (group_id, claim_id, decision_id, actor),
        )


async def create_group(db: aiosqlite.Connection, data: CanonicalGroupInput) -> dict:
    existing = await (await db.execute(
        f"SELECT id FROM claims WHERE id IN ({','.join('?' for _ in data.normalized_claim_ids)})",
        data.normalized_claim_ids,
    )).fetchall()
    if len(existing) != len(data.normalized_claim_ids):
        raise ConsolidationConflict("one or more normalized claims do not exist")
    try:
        cursor = await db.execute(
            """INSERT INTO claim_canonical_groups
               (canonical_text, subject_key, qualifier_summary, policy_revision)
               VALUES (?, ?, ?, ?)""",
            (data.canonical_text, data.subject_key,
             json.dumps(data.qualifier_summary, sort_keys=True), data.policy_revision),
        )
        await _append_memberships(
            db, cursor.lastrowid, data.normalized_claim_ids, None, data.actor
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_group(db, cursor.lastrowid)


async def _merge_groups(
    db: aiosqlite.Connection, target_id: int, source_id: int,
    decision_id: int, actor: str,
) -> None:
    members = await (await db.execute(
        """SELECT normalized_claim_id FROM claim_canonical_memberships
           WHERE canonical_group_id = ? AND retired_at IS NULL""",
        (source_id,),
    )).fetchall()
    await db.execute(
        """UPDATE claim_canonical_memberships SET retired_at = CURRENT_TIMESTAMP
           WHERE canonical_group_id = ? AND retired_at IS NULL""",
        (source_id,),
    )
    await db.execute(
        "UPDATE claim_canonical_groups SET retired_at = CURRENT_TIMESTAMP WHERE id = ?",
        (source_id,),
    )
    await _append_memberships(
        db, target_id, (row["normalized_claim_id"] for row in members), decision_id, actor
    )


async def _assign_equivalent_pair(
    db: aiosqlite.Connection, candidate: aiosqlite.Row,
    decision_id: int, actor: str, policy_revision: str,
) -> int:
    left = candidate["left_normalized_claim_id"]
    right = candidate["right_normalized_claim_id"]
    left_group = await _active_group_id(db, left)
    right_group = await _active_group_id(db, right)
    if left_group and right_group:
        if left_group != right_group:
            right_members = await (await db.execute(
                """SELECT normalized_claim_id FROM claim_canonical_memberships
                   WHERE canonical_group_id = ? AND retired_at IS NULL""",
                (right_group,),
            )).fetchall()
            for member in right_members:
                conflict = await _group_join_conflict(
                    db, left_group, member["normalized_claim_id"]
                )
                if conflict:
                    raise ConsolidationConflict(
                        f"cross-group compatibility requires review: {conflict}"
                    )
            await _merge_groups(db, min(left_group, right_group), max(left_group, right_group),
                                decision_id, actor)
        return min(left_group, right_group)
    group_id = left_group or right_group
    if group_id is None:
        claim = await (await db.execute(
            "SELECT claim_text FROM claims WHERE id = ?", (left,)
        )).fetchone()
        cursor = await db.execute(
            """INSERT INTO claim_canonical_groups
               (canonical_text, qualifier_summary, policy_revision)
               VALUES (?, '{}', ?)""",
            (claim["claim_text"], policy_revision),
        )
        group_id = cursor.lastrowid
    else:
        external_claim_id = right if left_group else left
        conflict = await _group_join_conflict(db, group_id, external_claim_id)
        if conflict:
            raise ConsolidationConflict(f"group compatibility requires review: {conflict}")
    await _append_memberships(db, group_id, (left, right), decision_id, actor)
    return group_id


async def decide_candidate(
    db: aiosqlite.Connection, candidate_id: int, data: EquivalenceDecisionInput
) -> dict:
    candidate = await (await db.execute(
        "SELECT * FROM claim_similarity_candidates WHERE id = ?", (candidate_id,)
    )).fetchone()
    if not candidate:
        raise LookupError("candidate not found")
    previous = await (await db.execute(
        """SELECT id FROM claim_equivalence_decisions WHERE candidate_id = ?
           ORDER BY created_at DESC, id DESC LIMIT 1""",
        (candidate_id,),
    )).fetchone()
    try:
        cursor = await db.execute(
            """INSERT INTO claim_equivalence_decisions
               (candidate_id, decision, rationale, compared_qualifiers, decider_type,
                decider_revision, actor, confidence, supersedes_decision_id)
               VALUES (?, ?, ?, ?, 'human', ?, ?, ?, ?)""",
            (candidate_id, data.decision, data.rationale,
             json.dumps(data.compared_qualifiers, sort_keys=True), data.decider_revision,
             data.actor, data.confidence, previous["id"] if previous else None),
        )
        group_id = None
        if data.decision == "equivalent":
            group_id = await _assign_equivalent_pair(
                db, candidate, cursor.lastrowid, data.actor, data.decider_revision
            )
        await db.execute(
            "UPDATE claim_similarity_candidates SET status = 'decided' WHERE id = ?",
            (candidate_id,),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"decision_id": cursor.lastrowid, "canonical_group_id": group_id}


async def record_model_shadow_decision(
    db: aiosqlite.Connection, data: ModelShadowDecisionInput
) -> dict:
    candidate = await (await db.execute(
        "SELECT id FROM claim_similarity_candidates WHERE id = ?", (data.candidate_id,)
    )).fetchone()
    if not candidate:
        raise LookupError("candidate not found")
    previous = await (await db.execute(
        """SELECT id FROM claim_equivalence_decisions WHERE candidate_id = ?
           ORDER BY created_at DESC, id DESC LIMIT 1""",
        (data.candidate_id,),
    )).fetchone()
    cursor = await db.execute(
        """INSERT INTO claim_equivalence_decisions
           (candidate_id, decision, rationale, compared_qualifiers, decider_type,
            decider_revision, confidence, supersedes_decision_id)
           VALUES (?, ?, ?, ?, 'model', ?, ?, ?)""",
        (data.candidate_id, data.decision, data.rationale,
         data.compared_qualifiers.model_dump_json(), data.decider_revision,
         data.confidence, previous["id"] if previous else None),
    )
    await db.execute(
        "UPDATE claim_similarity_candidates SET status = 'decided' WHERE id = ?",
        (data.candidate_id,),
    )
    await db.commit()
    return {"decision_id": cursor.lastrowid, "shadow": True, "grouped": False}


async def list_candidates(
    db: aiosqlite.Connection, status: str | None, decision: str | None,
    limit: int, offset: int,
) -> dict:
    filters = []
    params: list = []
    if status:
        filters.append("candidate.status = ?")
        params.append(status)
    if decision:
        filters.append("latest.decision = ?")
        params.append(decision)
    where = "WHERE " + " AND ".join(filters) if filters else ""
    rows = await (await db.execute(
        f"""SELECT candidate.*, left_claim.claim_text AS left_claim_text,
                    right_claim.claim_text AS right_claim_text,
                    latest.id AS decision_id, latest.decision, latest.rationale,
                    latest.compared_qualifiers, latest.decider_type,
                    latest.decider_revision, latest.actor, latest.confidence
             FROM claim_similarity_candidates candidate
             JOIN claims left_claim ON left_claim.id = candidate.left_normalized_claim_id
             JOIN claims right_claim ON right_claim.id = candidate.right_normalized_claim_id
             LEFT JOIN claim_equivalence_decisions latest ON latest.id = (
               SELECT id FROM claim_equivalence_decisions
               WHERE candidate_id = candidate.id ORDER BY created_at DESC, id DESC LIMIT 1)
             {where} ORDER BY candidate.id DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )).fetchall()
    total = (await (await db.execute(
        f"""SELECT COUNT(*) AS n FROM claim_similarity_candidates candidate
             LEFT JOIN claim_equivalence_decisions latest ON latest.id = (
               SELECT id FROM claim_equivalence_decisions
               WHERE candidate_id = candidate.id ORDER BY created_at DESC, id DESC LIMIT 1)
             {where}""",
        params,
    )).fetchone())["n"]
    items = []
    for row in rows:
        item = dict(row)
        item["compared_qualifiers"] = _json(item["compared_qualifiers"], {})
        items.append(item)
    return {"candidates": items, "total": total}


async def get_group(db: aiosqlite.Connection, group_id: int) -> dict | None:
    group = await (await db.execute(
        "SELECT * FROM claim_canonical_groups WHERE id = ?", (group_id,)
    )).fetchone()
    if not group:
        return None
    members = await (await db.execute(
        """SELECT membership.*, claim.claim_text, claim.claim_type,
                  (SELECT COUNT(*) FROM claim_occurrences occurrence
                   WHERE occurrence.normalized_claim_id = claim.id) AS occurrence_count
           FROM claim_canonical_memberships membership
           JOIN claims claim ON claim.id = membership.normalized_claim_id
           WHERE membership.canonical_group_id = ? ORDER BY membership.id""",
        (group_id,),
    )).fetchall()
    result = dict(group)
    result["qualifier_summary"] = _json(result["qualifier_summary"], {})
    result["members"] = []
    for member in members:
        item = dict(member)
        occurrences = await (await db.execute(
            """SELECT occurrence.id, occurrence.claim_text, occurrence.product_version,
                      occurrence.temporal_scope, occurrence.modality,
                      unit.source_locator, run.source_file, run.pipeline_slug
               FROM claim_occurrences occurrence
               JOIN claim_source_units unit ON unit.id = occurrence.source_unit_id
               JOIN claim_extraction_runs run ON run.id = unit.extraction_run_id
               WHERE occurrence.normalized_claim_id = ? ORDER BY occurrence.id""",
            (member["normalized_claim_id"],),
        )).fetchall()
        item["occurrences"] = [dict(occurrence) for occurrence in occurrences]
        result["members"].append(item)
    decisions = await (await db.execute(
        """SELECT decision.*, candidate.left_normalized_claim_id,
                  candidate.right_normalized_claim_id
           FROM claim_equivalence_decisions decision
           JOIN claim_similarity_candidates candidate ON candidate.id = decision.candidate_id
           WHERE candidate.left_normalized_claim_id IN (
             SELECT normalized_claim_id FROM claim_canonical_memberships
             WHERE canonical_group_id = ?)
             AND candidate.right_normalized_claim_id IN (
             SELECT normalized_claim_id FROM claim_canonical_memberships
             WHERE canonical_group_id = ?)
           ORDER BY decision.id""",
        (group_id, group_id),
    )).fetchall()
    result["decisions"] = [
        {**dict(decision),
         "compared_qualifiers": _json(decision["compared_qualifiers"], {})}
        for decision in decisions
    ]
    related = await (await db.execute(
        """SELECT candidate.id AS candidate_id, decision.decision,
                  candidate.left_normalized_claim_id,
                  candidate.right_normalized_claim_id, decision.rationale
           FROM claim_equivalence_decisions decision
           JOIN claim_similarity_candidates candidate ON candidate.id = decision.candidate_id
           WHERE decision.id = (
             SELECT id FROM claim_equivalence_decisions current
             WHERE current.candidate_id = candidate.id
             ORDER BY created_at DESC, id DESC LIMIT 1)
             AND decision.decision = 'related'
             AND (candidate.left_normalized_claim_id IN (
               SELECT normalized_claim_id FROM claim_canonical_memberships
               WHERE canonical_group_id = ? AND retired_at IS NULL)
               OR candidate.right_normalized_claim_id IN (
               SELECT normalized_claim_id FROM claim_canonical_memberships
               WHERE canonical_group_id = ? AND retired_at IS NULL))""",
        (group_id, group_id),
    )).fetchall()
    result["related_claims"] = [dict(item) for item in related]
    return result


async def list_groups(
    db: aiosqlite.Connection, include_retired: bool, limit: int, offset: int
) -> dict:
    where = "" if include_retired else "WHERE group_row.retired_at IS NULL"
    rows = await (await db.execute(
        f"""SELECT group_row.*,
                    COUNT(membership.id) AS member_count,
                    COALESCE(SUM((SELECT COUNT(*) FROM claim_occurrences occurrence
                      WHERE occurrence.normalized_claim_id = membership.normalized_claim_id)), 0)
                      AS occurrence_count
             FROM claim_canonical_groups group_row
             LEFT JOIN claim_canonical_memberships membership
               ON membership.canonical_group_id = group_row.id
              AND membership.retired_at IS NULL
             {where} GROUP BY group_row.id ORDER BY group_row.id DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )).fetchall()
    return {"groups": [{**dict(row), "qualifier_summary": _json(row["qualifier_summary"], {})}
                       for row in rows]}


async def split_group(
    db: aiosqlite.Connection, group_id: int, data: GroupSplitInput
) -> dict:
    placeholders = ",".join("?" for _ in data.normalized_claim_ids)
    active = await (await db.execute(
        f"""SELECT normalized_claim_id FROM claim_canonical_memberships
             WHERE canonical_group_id = ? AND retired_at IS NULL
               AND normalized_claim_id IN ({placeholders})""",
        (group_id, *data.normalized_claim_ids),
    )).fetchall()
    if len(active) != len(data.normalized_claim_ids):
        raise ConsolidationConflict("all split claims must be active members of the group")
    await db.execute(
        f"""UPDATE claim_canonical_memberships SET retired_at = CURRENT_TIMESTAMP
             WHERE canonical_group_id = ? AND retired_at IS NULL
               AND normalized_claim_id IN ({placeholders})""",
        (group_id, *data.normalized_claim_ids),
    )
    new_group_id = None
    if data.new_canonical_text:
        cursor = await db.execute(
            """INSERT INTO claim_canonical_groups
               (canonical_text, qualifier_summary, policy_revision) VALUES (?, '{}', ?)""",
            (data.new_canonical_text, data.policy_revision),
        )
        new_group_id = cursor.lastrowid
        await _append_memberships(
            db, new_group_id, data.normalized_claim_ids, None, data.actor
        )
    remaining = (await (await db.execute(
        """SELECT COUNT(*) AS n FROM claim_canonical_memberships
           WHERE canonical_group_id = ? AND retired_at IS NULL""", (group_id,)
    )).fetchone())["n"]
    if remaining == 0:
        await db.execute(
            "UPDATE claim_canonical_groups SET retired_at = CURRENT_TIMESTAMP WHERE id = ?",
            (group_id,),
        )
    await db.commit()
    return {"group_id": group_id, "new_group_id": new_group_id, "remaining": remaining}


async def retire_group(db: aiosqlite.Connection, group_id: int, actor: str) -> bool:
    group = await (await db.execute(
        "SELECT id FROM claim_canonical_groups WHERE id = ? AND retired_at IS NULL",
        (group_id,),
    )).fetchone()
    if not group:
        return False
    await db.execute(
        """UPDATE claim_canonical_memberships SET retired_at = CURRENT_TIMESTAMP
           WHERE canonical_group_id = ? AND retired_at IS NULL""", (group_id,)
    )
    await db.execute(
        "UPDATE claim_canonical_groups SET retired_at = CURRENT_TIMESTAMP WHERE id = ?",
        (group_id,),
    )
    await db.commit()
    return True


async def upsert_policy(
    db: aiosqlite.Connection, data: ConsolidationPolicyInput
) -> dict:
    if data.automatic_assignment_enabled and not data.kill_switch:
        evaluation = await (await db.execute(
            """SELECT * FROM claim_consolidation_evaluations
               WHERE evaluation_run_id = ?""",
            (data.evaluation_run_id,),
        )).fetchone()
        if not evaluation:
            raise ConsolidationConflict("policy evaluation run has not been recorded")
        if evaluation["labeled_dataset_revision"] != data.labeled_dataset_revision:
            raise ConsolidationConflict("policy dataset revision does not match evaluation")
        if evaluation["precision"] is None:
            raise ConsolidationConflict("evaluation has no automatic-equivalence precision")
        if evaluation["precision"] < data.minimum_precision:
            raise ConsolidationConflict("evaluation precision is below policy threshold")
        if data.evaluated_precision != evaluation["precision"]:
            raise ConsolidationConflict("policy precision must match recorded evaluation")
    await db.execute(
        """INSERT INTO claim_consolidation_policies
           (revision, automatic_assignment_enabled, kill_switch, minimum_confidence,
            minimum_precision, evaluated_precision, labeled_dataset_revision,
            evaluation_run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(revision) DO UPDATE SET
             automatic_assignment_enabled = excluded.automatic_assignment_enabled,
             kill_switch = excluded.kill_switch,
             minimum_confidence = excluded.minimum_confidence,
             minimum_precision = excluded.minimum_precision,
             evaluated_precision = excluded.evaluated_precision,
             labeled_dataset_revision = excluded.labeled_dataset_revision,
             evaluation_run_id = excluded.evaluation_run_id""",
        (
            data.revision,
            data.automatic_assignment_enabled,
            data.kill_switch,
            data.minimum_confidence,
            data.minimum_precision,
            data.evaluated_precision,
            data.labeled_dataset_revision,
            data.evaluation_run_id,
        ),
    )
    await db.commit()
    return dict(await (await db.execute(
        "SELECT * FROM claim_consolidation_policies WHERE revision = ?", (data.revision,)
    )).fetchone())


async def record_evaluation(
    db: aiosqlite.Connection, data: ConsolidationEvaluationInput
) -> dict:
    await db.execute(
        """INSERT INTO claim_consolidation_evaluations(
             evaluation_run_id, labeled_dataset_revision, retrieval_revision,
             decision_revision, candidate_count, labeled_pair_count,
             equivalent_prediction_count, true_positive_count, false_positive_count,
             false_negative_count, precision, recall, false_merge_rate,
             drift_summary, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(evaluation_run_id) DO UPDATE SET
             labeled_dataset_revision = excluded.labeled_dataset_revision,
             retrieval_revision = excluded.retrieval_revision,
             decision_revision = excluded.decision_revision,
             candidate_count = excluded.candidate_count,
             labeled_pair_count = excluded.labeled_pair_count,
             equivalent_prediction_count = excluded.equivalent_prediction_count,
             true_positive_count = excluded.true_positive_count,
             false_positive_count = excluded.false_positive_count,
             false_negative_count = excluded.false_negative_count,
             precision = excluded.precision,
             recall = excluded.recall,
             false_merge_rate = excluded.false_merge_rate,
             drift_summary = excluded.drift_summary,
             notes = excluded.notes""",
        (
            data.evaluation_run_id,
            data.labeled_dataset_revision,
            data.retrieval_revision,
            data.decision_revision,
            data.candidate_count,
            data.labeled_pair_count,
            data.equivalent_prediction_count,
            data.true_positive_count,
            data.false_positive_count,
            data.false_negative_count,
            data.precision,
            data.recall,
            data.false_merge_rate,
            json.dumps(data.drift_summary, sort_keys=True),
            data.notes,
        ),
    )
    await db.commit()
    row = await (await db.execute(
        """SELECT * FROM claim_consolidation_evaluations
           WHERE evaluation_run_id = ?""",
        (data.evaluation_run_id,),
    )).fetchone()
    result = dict(row)
    result["drift_summary"] = _json(result["drift_summary"], {})
    return result


async def list_evaluations(db: aiosqlite.Connection, limit: int) -> dict:
    rows = await (await db.execute(
        """SELECT * FROM claim_consolidation_evaluations
           ORDER BY created_at DESC, id DESC LIMIT ?""",
        (limit,),
    )).fetchall()
    return {
        "evaluations": [
            {**dict(row), "drift_summary": _json(row["drift_summary"], {})}
            for row in rows
        ]
    }


def _automatic_gate_status(
    evaluation: dict | None, minimum_precision: float, maximum_false_merge_rate: float
) -> dict:
    reasons = []
    if evaluation is None:
        return {"authorized": False, "reasons": ["missing evaluation_record"]}
    prediction_count = evaluation.get("equivalent_prediction_count") or 0
    precision = evaluation.get("precision")
    false_merge_rate = evaluation.get("false_merge_rate")
    if prediction_count <= 0:
        reasons.append("no automatic equivalent predictions were evaluated")
    if precision is None:
        reasons.append("automatic-equivalence precision is not measured")
    elif precision < minimum_precision:
        reasons.append(
            f"precision {precision:.6f} is below required {minimum_precision:.6f}"
        )
    if false_merge_rate is None:
        reasons.append("false-merge rate is not measured")
    elif false_merge_rate > maximum_false_merge_rate:
        reasons.append(
            "false-merge rate "
            f"{false_merge_rate:.6f} exceeds allowed {maximum_false_merge_rate:.6f}"
        )
    return {
        "authorized": not reasons,
        "reasons": reasons,
        "evaluation_run_id": evaluation.get("evaluation_run_id"),
        "labeled_dataset_revision": evaluation.get("labeled_dataset_revision"),
        "precision": precision,
        "false_merge_rate": false_merge_rate,
        "equivalent_prediction_count": prediction_count,
    }


def _reuse_gate_status(
    report: dict,
    minimum_agreement_rate: float,
    minimum_saved_tokens: int,
    require_zero_disagreements: bool,
) -> dict:
    simulation = report.get("simulation") or {}
    reasons = []
    agreement_rate = simulation.get("agreement_rate")
    simulated_count = simulation.get("simulated_reused_run_count") or 0
    disagreeing_count = simulation.get("simulated_disagreeing_reuse_count") or 0
    saved_tokens = simulation.get("estimated_saved_tokens") or 0
    if report.get("reuse_enabled"):
        reasons.append("reuse is already enabled; expected simulation-only evidence")
    if simulated_count <= 0:
        reasons.append("no simulated reused verification runs were measured")
    if agreement_rate is None:
        reasons.append("reuse agreement rate is not measured")
    elif agreement_rate < minimum_agreement_rate:
        reasons.append(
            f"agreement rate {agreement_rate:.6f} is below required {minimum_agreement_rate:.6f}"
        )
    if require_zero_disagreements and disagreeing_count > 0:
        reasons.append(f"{disagreeing_count} simulated reuse disagreements were found")
    if saved_tokens < minimum_saved_tokens:
        reasons.append(
            f"estimated saved tokens {saved_tokens} is below required {minimum_saved_tokens}"
        )
    return {
        "authorized": not reasons,
        "reasons": reasons,
        "simulated_reused_run_count": simulated_count,
        "simulated_disagreeing_reuse_count": disagreeing_count,
        "agreement_rate": agreement_rate,
        "estimated_saved_tokens": saved_tokens,
    }


async def consolidation_gate_status(
    db: aiosqlite.Connection,
    *,
    minimum_precision: float,
    maximum_false_merge_rate: float,
    minimum_reuse_agreement: float,
    minimum_saved_tokens: int,
    require_zero_reuse_disagreements: bool,
) -> dict:
    latest_evaluation = await (await db.execute(
        """SELECT * FROM claim_consolidation_evaluations
           ORDER BY created_at DESC, id DESC LIMIT 1"""
    )).fetchone()
    evaluation = None
    if latest_evaluation:
        evaluation = dict(latest_evaluation)
        evaluation["drift_summary"] = _json(evaluation["drift_summary"], {})
    reuse_report = await reuse_opportunities(db)
    return {
        "thresholds": {
            "minimum_precision": minimum_precision,
            "maximum_false_merge_rate": maximum_false_merge_rate,
            "minimum_reuse_agreement": minimum_reuse_agreement,
            "minimum_saved_tokens": minimum_saved_tokens,
            "require_zero_reuse_disagreements": require_zero_reuse_disagreements,
        },
        "latest_evaluation": evaluation,
        "automatic_assignment": _automatic_gate_status(
            evaluation, minimum_precision, maximum_false_merge_rate
        ),
        "verification_reuse": _reuse_gate_status(
            reuse_report,
            minimum_reuse_agreement,
            minimum_saved_tokens,
            require_zero_reuse_disagreements,
        ),
    }


async def apply_automatic_assignments(
    db: aiosqlite.Connection, policy_revision: str, limit: int
) -> dict:
    policy = await (await db.execute(
        "SELECT * FROM claim_consolidation_policies WHERE revision = ?",
        (policy_revision,),
    )).fetchone()
    if not policy:
        raise LookupError("consolidation policy not found")
    if not policy["automatic_assignment_enabled"] or policy["kill_switch"]:
        raise ConsolidationConflict("automatic assignment is disabled by policy")
    if (policy["evaluated_precision"] is None
            or policy["evaluated_precision"] < policy["minimum_precision"]
            or not policy["labeled_dataset_revision"]
            or not policy["evaluation_run_id"]):
        raise ConsolidationConflict("automatic policy has not passed its precision gate")
    evaluation = await (await db.execute(
        """SELECT precision, labeled_dataset_revision
           FROM claim_consolidation_evaluations WHERE evaluation_run_id = ?""",
        (policy["evaluation_run_id"],),
    )).fetchone()
    if (not evaluation
            or evaluation["labeled_dataset_revision"] != policy["labeled_dataset_revision"]
            or evaluation["precision"] != policy["evaluated_precision"]):
        raise ConsolidationConflict("automatic policy evaluation evidence is unavailable")
    rows = await (await db.execute(
        """SELECT candidate.*, decision.id AS decision_id,
                  decision.confidence, decision.decider_revision
           FROM claim_similarity_candidates candidate
           JOIN claim_equivalence_decisions decision ON decision.id = (
             SELECT id FROM claim_equivalence_decisions current
             WHERE current.candidate_id = candidate.id
             ORDER BY current.created_at DESC, current.id DESC LIMIT 1)
           WHERE decision.decision = 'equivalent'
             AND decision.decider_type IN ('deterministic', 'model')
             AND decision.confidence >= ?
             AND NOT EXISTS (
               SELECT 1 FROM claim_equivalence_decisions human
               WHERE human.candidate_id = candidate.id AND human.decider_type = 'human')
           ORDER BY candidate.id LIMIT ?""",
        (policy["minimum_confidence"], limit),
    )).fetchall()
    assigned = 0
    skipped_existing_group_merges = 0
    for candidate in rows:
        left_group = await _active_group_id(
            db, candidate["left_normalized_claim_id"]
        )
        right_group = await _active_group_id(
            db, candidate["right_normalized_claim_id"]
        )
        if left_group is not None and left_group == right_group:
            continue
        if left_group is not None and right_group is not None:
            skipped_existing_group_merges += 1
            continue
        group_id = left_group or right_group
        if group_id is not None:
            external_claim_id = (
                candidate["right_normalized_claim_id"]
                if left_group else candidate["left_normalized_claim_id"]
            )
            if await _group_join_conflict(db, group_id, external_claim_id):
                skipped_existing_group_merges += 1
                continue
        await _assign_equivalent_pair(
            db, candidate, candidate["decision_id"],
            f"automatic:{policy_revision}", policy_revision,
        )
        assigned += 1
    await db.commit()
    return {
        "policy_revision": policy_revision,
        "assigned": assigned,
        "skipped_existing_group_merges": skipped_existing_group_merges,
    }


async def consolidation_summary(db: aiosqlite.Connection) -> dict:
    row = await (await db.execute(
        """SELECT
          (SELECT COUNT(*) FROM claim_occurrences) AS occurrence_count,
          (SELECT COUNT(*) FROM claims) AS text_identity_count,
          (SELECT COUNT(*) FROM claim_canonical_groups WHERE retired_at IS NULL)
            AS canonical_group_count,
          (SELECT COUNT(*) FROM claim_similarity_candidates candidate
             WHERE candidate.status = 'pending' OR (
               SELECT decision FROM claim_equivalence_decisions
               WHERE candidate_id = candidate.id
               ORDER BY created_at DESC, id DESC LIMIT 1) = 'needs_review')
            AS unreviewed_candidate_count,
          (SELECT COUNT(*) FROM (
             SELECT canonical_group_id FROM claim_canonical_memberships
             WHERE retired_at IS NULL GROUP BY canonical_group_id HAVING COUNT(*) > 1
           )) AS multi_member_group_count"""
    )).fetchone()
    result = dict(row)
    result["multi_member_group_count"] = result["multi_member_group_count"] or 0
    return result


async def consolidation_metrics(db: aiosqlite.Connection) -> dict:
    overall = dict(await (await db.execute(
        """SELECT
          (SELECT COUNT(*) FROM claims) AS text_identity_count,
          (SELECT COUNT(DISTINCT normalized_claim_id)
             FROM claim_canonical_memberships WHERE retired_at IS NULL)
            AS grouped_text_identity_count,
          (SELECT COUNT(*) FROM claim_similarity_candidates) AS candidate_count,
          (SELECT COUNT(*) FROM claim_similarity_candidates candidate
             WHERE candidate.status = 'pending' OR (
               SELECT decision FROM claim_equivalence_decisions
               WHERE candidate_id = candidate.id
               ORDER BY created_at DESC, id DESC LIMIT 1) = 'needs_review')
            AS candidates_requiring_review,
          (SELECT COUNT(*) FROM claim_canonical_memberships
             WHERE retired_at IS NOT NULL) AS retired_membership_count,
          (SELECT AVG((julianday(decision.created_at) - julianday(claim.first_seen_at))
                       * 86400)
             FROM claim_equivalence_decisions decision
             JOIN claim_similarity_candidates candidate
               ON candidate.id = decision.candidate_id
             JOIN claims claim ON claim.id = candidate.right_normalized_claim_id)
            AS mean_seconds_to_decision"""
    )).fetchone())
    total = overall["text_identity_count"]
    overall["grouped_text_identity_rate"] = (
        overall["grouped_text_identity_count"] / total if total else None
    )
    decisions = await (await db.execute(
        """SELECT decision, COUNT(*) AS count
           FROM claim_equivalence_decisions current
           WHERE current.id = (
             SELECT id FROM claim_equivalence_decisions latest
             WHERE latest.candidate_id = current.candidate_id
             ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1)
           GROUP BY decision ORDER BY decision"""
    )).fetchall()
    latest_evaluation = await (await db.execute(
        """SELECT * FROM claim_consolidation_evaluations
           ORDER BY created_at DESC, id DESC LIMIT 1"""
    )).fetchone()
    corrections = await (await db.execute(
        """SELECT actor, COUNT(*) AS retired_membership_count
           FROM claim_canonical_memberships
           WHERE retired_at IS NOT NULL
           GROUP BY actor ORDER BY retired_membership_count DESC"""
    )).fetchall()
    breakdowns = {}
    dimensions = {
        "artifact_type": "run.artifact_type",
        "claim_type": "occurrence.claim_type",
        "extractor_revision": "run.extractor_revision",
        "product_version": "occurrence.product_version",
    }
    for name, expression in dimensions.items():
        rows = await (await db.execute(
            f"""SELECT COALESCE({expression}, 'unknown') AS value,
                       COUNT(DISTINCT occurrence.id) AS occurrence_count,
                       COUNT(DISTINCT occurrence.normalized_claim_id)
                         AS text_identity_count,
                       COUNT(DISTINCT membership.canonical_group_id)
                         AS canonical_group_count
                FROM claim_occurrences occurrence
                JOIN claim_source_units unit ON unit.id = occurrence.source_unit_id
                JOIN claim_extraction_runs run ON run.id = unit.extraction_run_id
                LEFT JOIN claim_canonical_memberships membership
                  ON membership.normalized_claim_id = occurrence.normalized_claim_id
                 AND membership.retired_at IS NULL
                GROUP BY COALESCE({expression}, 'unknown') ORDER BY value"""  # noqa: S608
        )).fetchall()
        breakdowns[name] = [dict(row) for row in rows]
    agreement = await (await db.execute(
        """SELECT membership.canonical_group_id,
                  COUNT(verification.id) AS verification_run_count,
                  COUNT(DISTINCT verification.verdict) AS verdict_count
           FROM claim_canonical_memberships membership
           JOIN claim_occurrences occurrence
             ON occurrence.normalized_claim_id = membership.normalized_claim_id
           JOIN claim_verification_runs verification
             ON verification.claim_occurrence_id = occurrence.id
           WHERE membership.retired_at IS NULL
           GROUP BY membership.canonical_group_id HAVING COUNT(verification.id) > 1"""
    )).fetchall()
    return {
        "overall": overall,
        "latest_decisions": {row["decision"]: row["count"] for row in decisions},
        "latest_evaluation": (
            {**dict(latest_evaluation),
             "drift_summary": _json(latest_evaluation["drift_summary"], {})}
            if latest_evaluation else None
        ),
        "corrections": {
            "retired_memberships_by_actor": [dict(row) for row in corrections],
        },
        "verification": {
            "multi_run_group_count": len(agreement),
            "agreeing_group_count": sum(row["verdict_count"] == 1 for row in agreement),
            "agreement_rate": (
                sum(row["verdict_count"] == 1 for row in agreement) / len(agreement)
                if agreement else None
            ),
        },
        "breakdowns": breakdowns,
    }


async def reuse_opportunities(db: aiosqlite.Connection) -> dict:
    rows = await (await db.execute(
        """SELECT membership.canonical_group_id, occurrence.product_version,
                  occurrence.temporal_scope, verification.evidence_context_digest,
                  verification.verifier_revision, verification.repository_revision,
                  verification.configuration_digest,
                  GROUP_CONCAT(verification.id) AS verification_run_ids,
                  GROUP_CONCAT(verification.verdict) AS verdicts,
                  GROUP_CONCAT(COALESCE(verification.token_count, 0)) AS token_counts,
                  GROUP_CONCAT(COALESCE(verification.cost_usd, 0)) AS costs,
                  COUNT(*) AS run_count,
                  COUNT(DISTINCT verification.verdict) AS verdict_count
           FROM claim_canonical_memberships membership
           JOIN claim_occurrences occurrence
             ON occurrence.normalized_claim_id = membership.normalized_claim_id
           JOIN claim_verification_runs verification
             ON verification.claim_occurrence_id = occurrence.id
           WHERE membership.retired_at IS NULL
             AND verification.evidence_context_digest IS NOT NULL
           GROUP BY membership.canonical_group_id, occurrence.product_version,
                    occurrence.temporal_scope, verification.evidence_context_digest,
                    verification.verifier_revision, verification.repository_revision,
                    verification.configuration_digest
           HAVING COUNT(*) > 1 ORDER BY run_count DESC"""
    )).fetchall()
    opportunities = []
    compatible_run_count = 0
    simulated_reused_run_count = 0
    simulated_agreeing_reuse_count = 0
    simulated_disagreeing_reuse_count = 0
    estimated_saved_tokens = 0
    estimated_saved_cost_usd = 0.0
    for row in rows:
        item = dict(row)
        verification_run_ids = [int(value) for value in item["verification_run_ids"].split(",")]
        verdicts = item.pop("verdicts").split(",")
        token_counts = [int(value) for value in item.pop("token_counts").split(",")]
        costs = [float(value) for value in item.pop("costs").split(",")]
        item["verification_run_ids"] = verification_run_ids
        item["agreement"] = item["verdict_count"] == 1
        item["source_verification_run_id"] = verification_run_ids[0]
        item["simulated_reused_verification_run_ids"] = verification_run_ids[1:]
        item["simulated_reuse_count"] = max(item["run_count"] - 1, 0)
        item["simulated_outcome"] = "agree" if item["agreement"] else "disagree"
        item["actual_verdicts"] = sorted(set(verdicts))
        item["estimated_saved_tokens"] = sum(token_counts[1:])
        item["estimated_saved_cost_usd"] = sum(costs[1:])
        compatible_run_count += item["run_count"]
        simulated_reused_run_count += item["simulated_reuse_count"]
        estimated_saved_tokens += item["estimated_saved_tokens"]
        estimated_saved_cost_usd += item["estimated_saved_cost_usd"]
        if item["agreement"]:
            simulated_agreeing_reuse_count += item["simulated_reuse_count"]
        else:
            simulated_disagreeing_reuse_count += item["simulated_reuse_count"]
        opportunities.append(item)
    invalidation_rows = await (await db.execute(
        """SELECT membership.canonical_group_id,
                  COUNT(verification.id) AS verification_run_count,
                  COUNT(DISTINCT occurrence.product_version) AS product_version_count,
                  COUNT(DISTINCT occurrence.temporal_scope) AS temporal_scope_count,
                  COUNT(DISTINCT verification.evidence_context_digest) AS evidence_context_count,
                  COUNT(DISTINCT verification.verifier_revision) AS verifier_revision_count,
                  COUNT(DISTINCT verification.repository_revision) AS repository_revision_count,
                  COUNT(DISTINCT verification.configuration_digest) AS configuration_digest_count
           FROM claim_canonical_memberships membership
           JOIN claim_occurrences occurrence
             ON occurrence.normalized_claim_id = membership.normalized_claim_id
           JOIN claim_verification_runs verification
             ON verification.claim_occurrence_id = occurrence.id
           WHERE membership.retired_at IS NULL
           GROUP BY membership.canonical_group_id
           HAVING COUNT(verification.id) > 1"""
    )).fetchall()
    invalidation_reasons = {
        "product_version": 0,
        "temporal_scope": 0,
        "evidence_context_digest": 0,
        "verifier_revision": 0,
        "repository_revision": 0,
        "configuration_digest": 0,
    }
    invalidated_groups = []
    for row in invalidation_rows:
        item = dict(row)
        reasons = []
        for key, count_key in (
            ("product_version", "product_version_count"),
            ("temporal_scope", "temporal_scope_count"),
            ("evidence_context_digest", "evidence_context_count"),
            ("verifier_revision", "verifier_revision_count"),
            ("repository_revision", "repository_revision_count"),
            ("configuration_digest", "configuration_digest_count"),
        ):
            if item[count_key] > 1:
                reasons.append(key)
                invalidation_reasons[key] += 1
        if reasons:
            invalidated_groups.append({
                "canonical_group_id": item["canonical_group_id"],
                "verification_run_count": item["verification_run_count"],
                "reasons": reasons,
            })
    return {
        "reuse_enabled": False,
        "reuse_policy": {
            "status": "simulation_only",
            "required_compatibility": [
                "canonical_group",
                "product_version",
                "temporal_scope",
                "evidence_context_digest",
                "verifier_revision",
                "repository_revision",
                "configuration_digest",
            ],
        },
        "opportunities": opportunities,
        "compatible_run_count": compatible_run_count,
        "simulation": {
            "simulated_reused_run_count": simulated_reused_run_count,
            "simulated_agreeing_reuse_count": simulated_agreeing_reuse_count,
            "simulated_disagreeing_reuse_count": simulated_disagreeing_reuse_count,
            "agreement_rate": (
                simulated_agreeing_reuse_count / simulated_reused_run_count
                if simulated_reused_run_count else None
            ),
            "estimated_saved_tokens": estimated_saved_tokens,
            "estimated_saved_cost_usd": estimated_saved_cost_usd,
        },
        "invalidation": {
            "groups_with_invalidation_count": len(invalidated_groups),
            "reason_group_counts": invalidation_reasons,
            "groups": invalidated_groups,
        },
    }
