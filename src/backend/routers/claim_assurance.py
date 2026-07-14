import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.crud.claim_assurance import (
    ExtractionRunConflict,
    HumanOverrideTargetConflict,
    create_explanation_run,
    create_extraction_run,
    create_human_override,
    create_regression_run,
    create_receipt_event,
    create_verification_run,
    get_effective_verdict,
    get_extraction_run,
    get_assurance_summary,
    list_extraction_runs,
    list_occurrences_for_verification,
    get_occurrence_history,
)
from backend.database import get_db
from backend.crud.claim_triage import (
    get_triage_explanation_facets,
    get_triage_issues,
    get_triage_summary,
    get_triage_types,
    list_triage_explanations,
    list_triage_occurrences,
)
from backend.schemas.claim_assurance import (
    ExplanationRunInput,
    ExtractionRunInput,
    HumanOverrideInput,
    RegressionRunInput,
    StageReceiptEventInput,
    VerificationRunInput,
)

router = APIRouter(prefix="/api/v2/claims", tags=["claim-assurance"])


@router.get("/summary")
async def assurance_summary(db: aiosqlite.Connection = Depends(get_db)):
    return await get_assurance_summary(db)


@router.get("/triage/summary")
async def triage_summary(db: aiosqlite.Connection = Depends(get_db)):
    return await get_triage_summary(db)


@router.get("/triage/types")
async def triage_types(db: aiosqlite.Connection = Depends(get_db)):
    return await get_triage_types(db)


@router.get("/triage/occurrences")
async def triage_occurrences(
    claim_type: str | None = Query(default=None, alias="type"),
    exclude_types: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    jira_key: str | None = Query(default=None),
    search: str | None = Query(default=None),
    source: str | None = Query(default=None),
    pipeline_slug: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    excluded = [value for value in (exclude_types or "").split(",") if value]
    return await list_triage_occurrences(
        db, claim_type, excluded, verdict, jira_key, search, source,
        sort, sort_dir, limit, offset, pipeline_slug=pipeline_slug,
    )


@router.get("/triage/issues")
async def triage_issues(
    sort: str = Query(default="contradicted"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_triage_issues(db, sort, sort_dir, limit, offset)


@router.get("/triage/explanations")
async def triage_explanations(
    category: str | None = Query(default=None),
    improvement_target: str | None = Query(default=None),
    jira_key: str | None = Query(default=None),
    human_review_required: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_triage_explanations(
        db, category, improvement_target, jira_key, human_review_required,
        limit, offset,
    )


@router.get("/triage/explanation-facets")
async def triage_explanation_facets(db: aiosqlite.Connection = Depends(get_db)):
    return await get_triage_explanation_facets(db)


@router.get("/extraction-runs")
async def extraction_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_extraction_runs(db, limit, offset)


@router.get("/extraction-runs/{run_id}")
async def extraction_run_detail(
    run_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    result = await get_extraction_run(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return result


@router.get("/occurrences")
async def verification_candidates(
    jira_key: str | None = Query(default=None),
    pending_only: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
):
    return {
        "occurrences": await list_occurrences_for_verification(
            db, jira_key, pending_only, limit
        )
    }


@router.post("/extraction-runs", status_code=201)
async def ingest_extraction_run(
    data: ExtractionRunInput, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await create_extraction_run(db, data)
    except ExtractionRunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/verification-runs", status_code=201)
async def ingest_verification_run(
    data: VerificationRunInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await create_verification_run(db, data)


@router.post("/explanation-runs", status_code=201)
async def ingest_explanation_run(
    data: ExplanationRunInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await create_explanation_run(db, data)


@router.post("/human-overrides", status_code=201)
async def ingest_human_override(
    data: HumanOverrideInput, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await create_human_override(db, data)
    except HumanOverrideTargetConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/regression-runs", status_code=201)
async def ingest_regression_run(
    data: RegressionRunInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await create_regression_run(db, data)


@router.post("/stage-receipts", status_code=201)
async def ingest_stage_receipt(
    data: StageReceiptEventInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await create_receipt_event(db, data)


@router.get("/occurrences/{occurrence_id}/history")
async def occurrence_history(
    occurrence_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    result = await get_occurrence_history(db, occurrence_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Claim occurrence not found")
    return result


@router.get("/occurrences/{occurrence_id}/effective-verdict")
async def effective_verdict(
    occurrence_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    result = await get_effective_verdict(db, occurrence_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No verification run found")
    return result
