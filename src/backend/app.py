import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator

import backend.metrics  # noqa: F401 – register custom Prometheus metrics

import backend.config
import backend.database
from backend.database import connect, disconnect, get_db, init_schema
from backend.collector.scheduler import collector_loop
from backend.logging_handler import log_handler
from backend.routers import health, pipeline_metadata, pipelines, runs, telemetry
from backend.routers import admin as admin_router
from backend.routers import collector as collector_router
from backend.routers import otlp as otlp_router
from backend.routers.provenance import run_router as provenance_run_router
from backend.routers.provenance import inventory_router as provenance_inventory_router
from backend.routers.mlflow_api import router as mlflow_router
from backend.routers.sboms import router as sboms_router
from backend.routers.sboms import provenance_vuln_router
from backend.routers.api_keys import router as api_keys_router
from backend.routers.credentials import router as credentials_router
from backend.routers.logs import router as logs_router
from backend.routers.artifacts import router as artifacts_router
from backend.routers.ci_definitions import router as ci_definitions_router
from backend.routers.hallucinations import router as hallucinations_router
from backend.routers.traces import router as traces_router
from backend.routers.otel_explorer import router as otel_explorer_router
from backend.routers.kb import router as kb_router
from backend.routers.chat import router as chat_router
from backend.routers.data_sources import router as data_sources_router
from backend.routers.claim_assurance import router as claim_assurance_router
from backend.routers.claim_consolidation import router as claim_consolidation_router

# Attach the ring-buffer log handler to collector and credential loggers
_collector_logger = logging.getLogger("backend.collector")
_collector_logger.addHandler(log_handler)
_collector_logger.setLevel(logging.DEBUG)

_creds_logger = logging.getLogger("backend.crud.credentials")
_creds_logger.addHandler(log_handler)
_creds_logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # If _db is already set (e.g. by the test fixture), skip connect/init_schema
    if backend.database._db is None:
        await connect()
        db = await get_db()
        await init_schema(db)

    task = asyncio.create_task(collector_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if backend.database._db is not None:
        await disconnect()


app = FastAPI(
    title="Agentic CI Observatory",
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(health.router)
app.include_router(admin_router.router)
app.include_router(pipelines.router)
app.include_router(pipeline_metadata.router)
app.include_router(runs.router)
app.include_router(collector_router.router)
app.include_router(telemetry.router)
app.include_router(otlp_router.router)
app.include_router(provenance_run_router)
app.include_router(provenance_inventory_router)
app.include_router(mlflow_router)
app.include_router(sboms_router)
app.include_router(provenance_vuln_router)
app.include_router(api_keys_router)
app.include_router(credentials_router)
app.include_router(logs_router)
app.include_router(artifacts_router)
app.include_router(ci_definitions_router)
app.include_router(hallucinations_router)
app.include_router(traces_router)
app.include_router(otel_explorer_router)
app.include_router(kb_router)
app.include_router(chat_router)
app.include_router(data_sources_router)
app.include_router(claim_assurance_router)
app.include_router(claim_consolidation_router)

static_dir = Path(backend.config.settings.static_dir)
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = static_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(static_dir / "index.html")
