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
from backend.crud.claim_reports import (
    DEFAULT_EXPORT_LIMIT,
    build_claim_assurance_report,
    create_claim_report_job,
    get_claim_report_artifact,
    get_claim_report_job,
    render_claim_assurance_markdown,
)
from backend.database import get_db
from backend.crud.claim_consolidation import generate_candidates
from backend.crud.claim_triage import (
    get_triage_explanation_facets,
    get_triage_issues,
    get_triage_summary,
    get_triage_types,
    list_triage_explanations,
    list_triage_occurrences,
)
from backend.schemas.claim_assurance import (
    ClaimReportJobInput,
    ExplanationRunInput,
    ExtractionRunInput,
    HumanOverrideInput,
    RegressionRunInput,
    StageReceiptEventInput,
    VerificationRunInput,
)
from backend.schemas.claim_consolidation import CandidateGenerationInput
from fastapi.responses import PlainTextResponse, Response

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


def _report_filters(
    jira_key: str | None,
    claim_occurrence_id: int | None,
    normalized_claim_id: int | None,
    canonical_group_id: int | None,
    artifact_type: str | None,
    pipeline_slug: str | None,
    source_file: str | None,
    claim_type: str | None,
    verdict: str | None,
    processing_state: str | None,
    explanation_category: str | None,
    improvement_target: str | None,
    human_review_required: bool | None,
    created_after: str | None,
    created_before: str | None,
) -> dict:
    return {
        "jira_key": jira_key,
        "claim_occurrence_id": claim_occurrence_id,
        "normalized_claim_id": normalized_claim_id,
        "canonical_group_id": canonical_group_id,
        "artifact_type": artifact_type,
        "pipeline_slug": pipeline_slug,
        "source_file": source_file,
        "claim_type": claim_type,
        "verdict": verdict,
        "processing_state": processing_state,
        "explanation_category": explanation_category,
        "improvement_target": improvement_target,
        "human_review_required": human_review_required,
        "created_after": created_after,
        "created_before": created_before,
    }


@router.get("/reports/export.json")
async def export_report_json(
    jira_key: str | None = None,
    claim_occurrence_id: int | None = Query(default=None, gt=0),
    normalized_claim_id: int | None = Query(default=None, gt=0),
    canonical_group_id: int | None = Query(default=None, gt=0),
    artifact_type: str | None = None,
    pipeline_slug: str | None = None,
    source_file: str | None = None,
    claim_type: str | None = None,
    verdict: str | None = Query(
        default=None,
        pattern="^(pending|supported|contradicted|insufficient_evidence|not_applicable)$",
    ),
    processing_state: str | None = Query(
        default=None,
        pattern="^(not_verified|verified_without_explanation|explanation_requires_human_review|explained)$",
    ),
    explanation_category: str | None = None,
    improvement_target: str | None = None,
    human_review_required: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    observatory_url: str | None = None,
    limit: int = Query(default=DEFAULT_EXPORT_LIMIT, ge=1, le=5000),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await build_claim_assurance_report(
        db,
        _report_filters(
            jira_key, claim_occurrence_id, normalized_claim_id, canonical_group_id,
            artifact_type, pipeline_slug, source_file, claim_type, verdict,
            processing_state, explanation_category, improvement_target,
            human_review_required, created_after, created_before,
        ),
        observatory_url=observatory_url,
        limit=limit,
    )


@router.get("/reports/export.md", response_class=PlainTextResponse)
async def export_report_markdown(
    jira_key: str | None = None,
    claim_occurrence_id: int | None = Query(default=None, gt=0),
    normalized_claim_id: int | None = Query(default=None, gt=0),
    canonical_group_id: int | None = Query(default=None, gt=0),
    artifact_type: str | None = None,
    pipeline_slug: str | None = None,
    source_file: str | None = None,
    claim_type: str | None = None,
    verdict: str | None = Query(
        default=None,
        pattern="^(pending|supported|contradicted|insufficient_evidence|not_applicable)$",
    ),
    processing_state: str | None = Query(
        default=None,
        pattern="^(not_verified|verified_without_explanation|explanation_requires_human_review|explained)$",
    ),
    explanation_category: str | None = None,
    improvement_target: str | None = None,
    human_review_required: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    observatory_url: str | None = None,
    limit: int = Query(default=DEFAULT_EXPORT_LIMIT, ge=1, le=5000),
    db: aiosqlite.Connection = Depends(get_db),
):
    report = await build_claim_assurance_report(
        db,
        _report_filters(
            jira_key, claim_occurrence_id, normalized_claim_id, canonical_group_id,
            artifact_type, pipeline_slug, source_file, claim_type, verdict,
            processing_state, explanation_category, improvement_target,
            human_review_required, created_after, created_before,
        ),
        observatory_url=observatory_url,
        limit=limit,
    )
    return render_claim_assurance_markdown(report)


@router.post("/reports", status_code=201)
async def create_report_job(
    data: ClaimReportJobInput, db: aiosqlite.Connection = Depends(get_db)
):
    return await create_claim_report_job(
        db,
        report_format=data.report_format,
        filters=data.filters,
        observatory_url=data.observatory_url,
        limit=data.limit,
    )


@router.get("/reports/{report_id}/download")
async def report_job_download(
    report_id: int,
    report_format: str = Query(default="json", alias="format", pattern="^(json|markdown)$"),
    db: aiosqlite.Connection = Depends(get_db),
):
    artifact = await get_claim_report_artifact(db, report_id, report_format)
    if artifact is None:
        raise HTTPException(status_code=404, detail="report artifact not found")
    content, media_type = artifact
    return Response(content=content, media_type=media_type)


@router.get("/reports/{report_id}")
async def report_job_detail(
    report_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    result = await get_claim_report_job(db, report_id)
    if result is None:
        raise HTTPException(status_code=404, detail="report job not found")
    return result


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
        result = await create_extraction_run(db, data)
        if result.get("created") and result["occurrence_ids"]:
            rows = await (await db.execute(
                """SELECT DISTINCT normalized_claim_id FROM claim_occurrences
                   WHERE id IN ({})""".format(
                    ",".join("?" for _ in result["occurrence_ids"])
                ),
                result["occurrence_ids"],
            )).fetchall()
            created_candidates = 0
            for row in rows:
                generated = await generate_candidates(db, CandidateGenerationInput(
                    run_key=(
                        f"ingestion:{result['id']}:{row['normalized_claim_id']}:sqlite-fts5-v1"
                    ),
                    retrieval_revision="sqlite-fts5-v1",
                    claim_id=row["normalized_claim_id"],
                    batch_size=1,
                    shortlist_size=10,
                ))
                created_candidates += generated["created"]
            result["candidate_generation"] = {
                "retrieval_revision": "sqlite-fts5-v1",
                "created": created_candidates,
            }
        return result
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
