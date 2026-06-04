from typing import Optional

from pydantic import BaseModel


class RunResponse(BaseModel):
    id: int
    pipeline_id: int
    external_id: str
    job: Optional[str] = None
    queued_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str
    ref: Optional[str] = None
    web_url: Optional[str] = None
    artifacts_scraped: Optional[bool] = False
    created_at: Optional[str] = None


class RunListResponse(BaseModel):
    runs: list[RunResponse]
    total: int
    page: int
    per_page: int
