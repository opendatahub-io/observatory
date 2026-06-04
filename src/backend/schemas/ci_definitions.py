from typing import Optional

from pydantic import BaseModel


class CIJobScript(BaseModel):
    phase: str
    step_order: int
    command: str


class CIJobVariable(BaseModel):
    key: str
    value: Optional[str] = None
    masked: bool = False


class CIJobResponse(BaseModel):
    id: int
    name: str
    stage: Optional[str] = None
    image: Optional[str] = None
    timeout: Optional[str] = None
    extends: Optional[str] = None
    resource_group: Optional[str] = None
    allow_failure: bool = False
    tags: list[str] = []
    variables: list[CIJobVariable] = []
    scripts: list[CIJobScript] = []


class CIJobListResponse(BaseModel):
    jobs: list[CIJobResponse]
    total: int


class CIIncludeResponse(BaseModel):
    id: int
    include_type: str
    project: Optional[str] = None
    file: Optional[str] = None
    ref: Optional[str] = None


class CIDefinitionResponse(BaseModel):
    jobs: list[CIJobResponse]
    includes: list[CIIncludeResponse]


class ImageInventoryItem(BaseModel):
    image: str
    pipelines: list[str]
    job_count: int


class TagInventoryItem(BaseModel):
    tag: str
    pipelines: list[str]
    job_count: int
