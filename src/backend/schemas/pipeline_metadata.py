from typing import Optional

from pydantic import BaseModel


# --- Images ---

class PipelineImageCreate(BaseModel):
    name: Optional[str] = None
    ref: str


class PipelineImageResponse(BaseModel):
    id: int
    pipeline_id: int
    name: Optional[str] = None
    ref: str


# --- Skills ---

class PipelineSkillCreate(BaseModel):
    repo_url: str
    branch: Optional[str] = None
    purpose: Optional[str] = None


class PipelineSkillResponse(BaseModel):
    id: int
    pipeline_id: int
    repo_url: str
    branch: Optional[str] = None
    purpose: Optional[str] = None


# --- Shared Libs ---

class PipelineSharedLibCreate(BaseModel):
    repo_url: str
    purpose: Optional[str] = None


class PipelineSharedLibResponse(BaseModel):
    id: int
    pipeline_id: int
    repo_url: str
    purpose: Optional[str] = None


# --- Jira Contracts ---

class PipelineJiraContractCreate(BaseModel):
    project: str
    labels_applied: Optional[list[str]] = None


class PipelineJiraContractResponse(BaseModel):
    id: int
    pipeline_id: int
    project: str
    labels_applied: Optional[list[str]] = None


# --- Telemetry Config ---

class PipelineTelemetryConfigCreate(BaseModel):
    collector_type: Optional[str] = None
    endpoint: Optional[str] = None
    summary_script: Optional[str] = None
    status: Optional[str] = "active"


class PipelineTelemetryConfigResponse(BaseModel):
    id: int
    pipeline_id: int
    collector_type: Optional[str] = None
    endpoint: Optional[str] = None
    summary_script: Optional[str] = None
    status: Optional[str] = "active"


# --- Artifact Config ---

class PipelineArtifactConfigCreate(BaseModel):
    results_repo: Optional[str] = None
    status: Optional[str] = "active"


class PipelineArtifactConfigResponse(BaseModel):
    id: int
    pipeline_id: int
    results_repo: Optional[str] = None
    status: Optional[str] = "active"
