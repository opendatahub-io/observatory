from typing import Optional

from pydantic import BaseModel

from backend.schemas.pipeline_metadata import (
    PipelineImageResponse,
    PipelineSkillResponse,
    PipelineSharedLibResponse,
    PipelineJiraContractResponse,
    PipelineTelemetryConfigResponse,
    PipelineArtifactConfigResponse,
)


class PipelineCreate(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    owner: Optional[str] = None
    repo_url: str
    platform: str
    platform_project_id: Optional[str] = None
    cron: Optional[str] = None
    expected_interval_minutes: Optional[int] = None
    timeout_minutes: Optional[int] = None
    status: Optional[str] = "production"
    group: Optional[str] = None
    display_order: Optional[int] = None
    jobs: Optional[list[str]] = None
    job_patterns: Optional[list[str]] = None


class PipelineUpdate(BaseModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    repo_url: Optional[str] = None
    platform: Optional[str] = None
    platform_project_id: Optional[str] = None
    cron: Optional[str] = None
    expected_interval_minutes: Optional[int] = None
    timeout_minutes: Optional[int] = None
    status: Optional[str] = None
    group: Optional[str] = None
    display_order: Optional[int] = None
    jobs: Optional[list[str]] = None
    job_patterns: Optional[list[str]] = None


class PipelineResponse(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    owner: Optional[str] = None
    repo_url: str
    platform: str
    platform_project_id: Optional[str] = None
    cron: Optional[str] = None
    expected_interval_minutes: Optional[int] = None
    timeout_minutes: Optional[int] = None
    status: Optional[str] = "production"
    group: Optional[str] = None
    display_order: Optional[int] = None
    jobs: Optional[list[str]] = None
    job_patterns: Optional[list[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    health: str = "grey"
    images: Optional[list[PipelineImageResponse]] = None
    skills: Optional[list[PipelineSkillResponse]] = None
    shared_libs: Optional[list[PipelineSharedLibResponse]] = None
    jira_contracts: Optional[list[PipelineJiraContractResponse]] = None
    telemetry_config: Optional[list[PipelineTelemetryConfigResponse]] = None
    artifact_config: Optional[list[PipelineArtifactConfigResponse]] = None


class PipelineListResponse(BaseModel):
    pipelines: list[PipelineResponse]
