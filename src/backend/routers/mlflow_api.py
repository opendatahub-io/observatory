"""MLflow REST API compatibility layer.

Implements the subset of the MLflow REST API that the standard ``mlflow``
Python client uses, so that users can point their tracking URI at Observatory
and push experiments, runs, metrics, and params without any code changes.
"""

import uuid
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.auth import require_api_key
from backend.database import get_db

# ---------------------------------------------------------------------------
# Pydantic models for request / response bodies
# ---------------------------------------------------------------------------


class CreateExperimentRequest(BaseModel):
    name: str


class CreateExperimentResponse(BaseModel):
    experiment_id: str


class ExperimentInfo(BaseModel):
    experiment_id: str
    name: str
    lifecycle_stage: str = "active"


class SearchExperimentsResponse(BaseModel):
    experiments: List[ExperimentInfo]


class CreateRunRequest(BaseModel):
    experiment_id: str
    start_time: Optional[int] = None
    run_name: Optional[str] = None
    tags: Optional[List[Dict[str, str]]] = None


class RunInfo(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    start_time: Optional[int] = None
    end_time: Optional[int] = None


class RunData(BaseModel):
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    params: List[Dict[str, str]] = Field(default_factory=list)


class RunObject(BaseModel):
    info: RunInfo
    data: RunData = Field(default_factory=RunData)


class CreateRunResponse(BaseModel):
    run: RunObject


class UpdateRunRequest(BaseModel):
    run_id: str
    status: Optional[str] = None
    end_time: Optional[int] = None
    run_name: Optional[str] = None


class UpdateRunResponse(BaseModel):
    run_info: RunInfo


class LogMetricRequest(BaseModel):
    run_id: str
    key: str
    value: float
    timestamp: Optional[int] = None
    step: int = 0


class LogParamRequest(BaseModel):
    run_id: str
    key: str
    value: str


class SearchRunsRequest(BaseModel):
    experiment_ids: Optional[List[str]] = None
    filter: Optional[str] = None  # noqa: A003 – MLflow API uses 'filter'
    max_results: int = 100


class SearchRunsResponse(BaseModel):
    runs: List[RunObject]


class GetRunResponse(BaseModel):
    run: RunObject


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

PREFIX = "/mlflow/api/2.0/mlflow"

router = APIRouter(tags=["mlflow"])


# -- Experiments ------------------------------------------------------------


@router.post(f"{PREFIX}/experiments/create", dependencies=[Depends(require_api_key)])
async def create_experiment(
    body: CreateExperimentRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> CreateExperimentResponse:
    # Generate a new numeric experiment_id (MAX + 1 strategy)
    cursor = await db.execute(
        "SELECT COALESCE(MAX(CAST(experiment_id AS INTEGER)), 0) + 1 FROM mlflow_experiments"
    )
    row = await cursor.fetchone()
    experiment_id = str(row[0])

    await db.execute(
        "INSERT INTO mlflow_experiments (experiment_id, name) VALUES (?, ?)",
        (experiment_id, body.name),
    )
    await db.commit()
    return CreateExperimentResponse(experiment_id=experiment_id)


@router.get(f"{PREFIX}/experiments/search")
@router.post(f"{PREFIX}/experiments/search")
async def search_experiments(
    filter: Optional[str] = Query(default=None, alias="filter"),  # noqa: A002
    max_results: int = Query(default=1000),
    db: aiosqlite.Connection = Depends(get_db),
) -> SearchExperimentsResponse:
    cursor = await db.execute(
        "SELECT experiment_id, name FROM mlflow_experiments LIMIT ?",
        (max_results,),
    )
    rows = await cursor.fetchall()
    experiments = [
        ExperimentInfo(experiment_id=r["experiment_id"], name=r["name"])
        for r in rows
    ]
    return SearchExperimentsResponse(experiments=experiments)


# -- Runs -------------------------------------------------------------------


@router.post(f"{PREFIX}/runs/create", dependencies=[Depends(require_api_key)])
async def create_run(
    body: CreateRunRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> CreateRunResponse:
    run_id = uuid.uuid4().hex
    status = "RUNNING"

    await db.execute(
        "INSERT INTO mlflow_runs (run_id, experiment_id, status, start_time) VALUES (?, ?, ?, ?)",
        (run_id, body.experiment_id, status, body.start_time),
    )
    await db.commit()

    info = RunInfo(
        run_id=run_id,
        experiment_id=body.experiment_id,
        status=status,
        start_time=body.start_time,
    )
    return CreateRunResponse(run=RunObject(info=info))


@router.post(f"{PREFIX}/runs/update", dependencies=[Depends(require_api_key)])
async def update_run(
    body: UpdateRunRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> UpdateRunResponse:
    sets: list[str] = []
    params: list[Any] = []

    if body.status is not None:
        sets.append("status = ?")
        params.append(body.status)
    if body.end_time is not None:
        sets.append("end_time = ?")
        params.append(body.end_time)

    if sets:
        params.append(body.run_id)
        await db.execute(
            f"UPDATE mlflow_runs SET {', '.join(sets)} WHERE run_id = ?",
            params,
        )
        await db.commit()

    cursor = await db.execute(
        "SELECT run_id, experiment_id, status, start_time, end_time FROM mlflow_runs WHERE run_id = ?",
        (body.run_id,),
    )
    row = await cursor.fetchone()
    info = RunInfo(
        run_id=row["run_id"],
        experiment_id=row["experiment_id"],
        status=row["status"],
        start_time=row["start_time"],
        end_time=row["end_time"],
    )
    return UpdateRunResponse(run_info=info)


# -- Metrics & Params -------------------------------------------------------


@router.post(f"{PREFIX}/runs/log-metric", dependencies=[Depends(require_api_key)])
async def log_metric(
    body: LogMetricRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    await db.execute(
        "INSERT INTO mlflow_metrics (run_id, key, value, timestamp, step) VALUES (?, ?, ?, ?, ?)",
        (body.run_id, body.key, body.value, body.timestamp, body.step),
    )
    await db.commit()
    return {}


@router.post(f"{PREFIX}/runs/log-param", dependencies=[Depends(require_api_key)])
async def log_param(
    body: LogParamRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    await db.execute(
        "INSERT INTO mlflow_params (run_id, key, value) VALUES (?, ?, ?)",
        (body.run_id, body.key, body.value),
    )
    await db.commit()
    return {}


# -- Run retrieval -----------------------------------------------------------


async def _build_run_object(
    db: aiosqlite.Connection, row: aiosqlite.Row
) -> RunObject:
    """Assemble a full RunObject from a mlflow_runs row."""
    run_id = row["run_id"]

    # Fetch metrics
    mcursor = await db.execute(
        "SELECT key, value, timestamp, step FROM mlflow_metrics WHERE run_id = ?",
        (run_id,),
    )
    metrics_rows = await mcursor.fetchall()
    metrics = [
        {"key": m["key"], "value": m["value"], "timestamp": m["timestamp"], "step": m["step"]}
        for m in metrics_rows
    ]

    # Fetch params
    pcursor = await db.execute(
        "SELECT key, value FROM mlflow_params WHERE run_id = ?",
        (run_id,),
    )
    params_rows = await pcursor.fetchall()
    params = [{"key": p["key"], "value": p["value"]} for p in params_rows]

    info = RunInfo(
        run_id=row["run_id"],
        experiment_id=row["experiment_id"],
        status=row["status"],
        start_time=row["start_time"],
        end_time=row["end_time"],
    )
    data = RunData(metrics=metrics, params=params)
    return RunObject(info=info, data=data)


@router.get(f"{PREFIX}/runs/get")
async def get_run(
    run_id: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
) -> GetRunResponse:
    cursor = await db.execute(
        "SELECT run_id, experiment_id, status, start_time, end_time FROM mlflow_runs WHERE run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    run = await _build_run_object(db, row)
    return GetRunResponse(run=run)


@router.post(f"{PREFIX}/runs/search")
async def search_runs(
    body: SearchRunsRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> SearchRunsResponse:
    query = "SELECT run_id, experiment_id, status, start_time, end_time FROM mlflow_runs"
    params: list[Any] = []

    if body.experiment_ids:
        placeholders = ", ".join("?" for _ in body.experiment_ids)
        query += f" WHERE experiment_id IN ({placeholders})"
        params.extend(body.experiment_ids)

    query += " LIMIT ?"
    params.append(body.max_results)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    runs = [await _build_run_object(db, r) for r in rows]
    return SearchRunsResponse(runs=runs)
