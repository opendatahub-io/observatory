import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.crud.claim_consolidation import (
    ConsolidationConflict,
    apply_automatic_assignments,
    consolidation_metrics,
    consolidation_gate_status,
    consolidation_summary,
    create_group,
    decide_candidate,
    generate_candidates,
    get_group,
    list_evaluations,
    list_candidates,
    list_groups,
    record_evaluation,
    record_model_shadow_decision,
    retire_group,
    reuse_opportunities,
    run_shadow_decisions,
    split_group,
    upsert_policy,
)
from backend.database import get_db
from backend.schemas.claim_consolidation import (
    CandidateGenerationInput,
    CanonicalGroupInput,
    ConsolidationEvaluationInput,
    ConsolidationPolicyInput,
    EquivalenceDecisionInput,
    GroupRetirementInput,
    GroupSplitInput,
    ModelShadowDecisionInput,
    ShadowDecisionInput,
)


router = APIRouter(prefix="/api/v2/claim-consolidation", tags=["claim-consolidation"])


def _conflict(exc: ConsolidationConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/summary")
async def summary(db: aiosqlite.Connection = Depends(get_db)):
    return await consolidation_summary(db)


@router.get("/metrics")
async def metrics(db: aiosqlite.Connection = Depends(get_db)):
    return await consolidation_metrics(db)


@router.get("/gate-status")
async def gate_status(
    minimum_precision: float = Query(default=0.99, ge=0, le=1),
    maximum_false_merge_rate: float = Query(default=0.01, ge=0, le=1),
    minimum_reuse_agreement: float = Query(default=1.0, ge=0, le=1),
    minimum_saved_tokens: int = Query(default=1, ge=0),
    require_zero_reuse_disagreements: bool = True,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await consolidation_gate_status(
        db,
        minimum_precision=minimum_precision,
        maximum_false_merge_rate=maximum_false_merge_rate,
        minimum_reuse_agreement=minimum_reuse_agreement,
        minimum_saved_tokens=minimum_saved_tokens,
        require_zero_reuse_disagreements=require_zero_reuse_disagreements,
    )


@router.post("/candidates/generate")
async def candidate_generation(
    data: CandidateGenerationInput, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await generate_candidates(db, data)
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.post("/decisions/shadow")
async def shadow_decisions(
    data: ShadowDecisionInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await run_shadow_decisions(db, data.decision_revision, data.limit)


@router.post("/decisions/model-shadow", status_code=201)
async def model_shadow_decision(
    data: ModelShadowDecisionInput, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await record_model_shadow_decision(db, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluations", status_code=201)
async def evaluation_record(
    data: ConsolidationEvaluationInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await record_evaluation(db, data)


@router.get("/evaluations")
async def evaluations(
    limit: int = Query(default=20, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_evaluations(db, limit)


@router.get("/candidates")
async def candidates(
    status: str | None = Query(default=None, pattern="^(pending|decided|dismissed)$"),
    decision: str | None = Query(
        default=None, pattern="^(equivalent|related|distinct|needs_review)$"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_candidates(db, status, decision, limit, offset)


@router.post("/candidates/{candidate_id}/decisions", status_code=201)
async def candidate_decision(
    candidate_id: int, data: EquivalenceDecisionInput,
    db: aiosqlite.Connection = Depends(get_db),
):
    try:
        return await decide_candidate(db, candidate_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.get("/groups")
async def groups(
    include_retired: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_groups(db, include_retired, limit, offset)


@router.post("/groups", status_code=201)
async def group_create(
    data: CanonicalGroupInput, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await create_group(db, data)
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.get("/groups/{group_id}")
async def group_detail(
    group_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    result = await get_group(db, group_id)
    if result is None:
        raise HTTPException(status_code=404, detail="canonical group not found")
    return result


@router.post("/groups/{group_id}/split")
async def group_split(
    group_id: int, data: GroupSplitInput,
    db: aiosqlite.Connection = Depends(get_db),
):
    try:
        return await split_group(db, group_id, data)
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.post("/groups/{group_id}/retire")
async def group_retire(
    group_id: int, data: GroupRetirementInput,
    db: aiosqlite.Connection = Depends(get_db),
):
    if not await retire_group(db, group_id, data.actor):
        raise HTTPException(status_code=404, detail="active canonical group not found")
    return {"retired": True, "rationale": data.rationale}


@router.put("/policies/{revision}")
async def policy_update(
    revision: str, data: ConsolidationPolicyInput,
    db: aiosqlite.Connection = Depends(get_db),
):
    if revision != data.revision:
        raise HTTPException(status_code=422, detail="policy revision path mismatch")
    try:
        return await upsert_policy(db, data)
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.post("/automatic/{policy_revision}")
async def automatic_assignment(
    policy_revision: str,
    limit: int = Query(default=100, ge=1, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
):
    try:
        return await apply_automatic_assignments(db, policy_revision, limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConsolidationConflict as exc:
        raise _conflict(exc) from exc


@router.get("/verification-reuse-opportunities")
async def verification_reuse_report(
    db: aiosqlite.Connection = Depends(get_db),
):
    return await reuse_opportunities(db)
