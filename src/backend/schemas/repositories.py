from typing import Literal, Optional

from pydantic import BaseModel

RepoKind = Literal["pipeline_source", "skill", "shared_lib", "results"]
RepoStatus = Literal["active", "inactive", "archived"]


class RepositoryCreate(BaseModel):
    domain: str
    owner: str
    name: str
    kind: RepoKind
    git_url: str
    description: Optional[str] = None
    status: RepoStatus = "active"
    default_branch: str = "main"


class RepositoryUpdate(BaseModel):
    description: Optional[str] = None
    status: Optional[RepoStatus] = None
    default_branch: Optional[str] = None


class RepositoryResponse(BaseModel):
    id: int
    domain: str
    owner: str
    name: str
    kind: RepoKind
    git_url: str
    description: Optional[str] = None
    status: RepoStatus
    default_branch: str
    checkout_path: str
    last_synced_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    last_sync_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LinkedPipeline(BaseModel):
    pipeline_id: int
    slug: str
    name: str
    relation: str
    purpose: Optional[str] = None
    branch: Optional[str] = None


class RepositoryDetailResponse(RepositoryResponse):
    linked_pipelines: list[LinkedPipeline] = []


class SyncResult(BaseModel):
    status: str
    path: Optional[str] = None
    error: Optional[str] = None
