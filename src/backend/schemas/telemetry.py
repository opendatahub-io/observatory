from typing import Optional

from pydantic import BaseModel


class TelemetrySummaryResponse(BaseModel):
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    run_count: int = 0
    pipeline_slug: Optional[str] = None


class TelemetryTrendPoint(BaseModel):
    date: str
    total_tokens: int = 0
    cost_usd: float = 0.0
    run_count: int = 0


class TelemetryTrendsResponse(BaseModel):
    trends: list[TelemetryTrendPoint]


class CostBreakdownItem(BaseModel):
    pipeline_slug: str
    pipeline_name: str
    model: Optional[str] = None
    skill_name: Optional[str] = None
    total_cost: float = 0.0
    total_tokens: int = 0
    run_count: int = 0


class CostBreakdownResponse(BaseModel):
    breakdown: list[CostBreakdownItem]


class PipelineTelemetryRow(BaseModel):
    id: int
    pipeline_run_id: int
    total_tokens: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    model: Optional[str] = None
    skill_name: Optional[str] = None
    duration_ms: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    run_external_id: str
    run_started_at: Optional[str] = None


class PipelineTelemetryResponse(BaseModel):
    pipeline_slug: str
    rows: list[PipelineTelemetryRow]
    total_tokens: int = 0
    total_cost: float = 0.0
    run_count: int = 0
