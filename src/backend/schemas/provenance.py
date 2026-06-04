from typing import Optional

from pydantic import BaseModel


class CommandResponse(BaseModel):
    id: int
    pipeline_run_id: int
    step_order: int
    command: str
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[str] = None


class PackageResponse(BaseModel):
    id: int
    pipeline_run_id: int
    manager: str
    name: str
    version: str
    source: Optional[str] = None
    created_at: Optional[str] = None


class ContainerResponse(BaseModel):
    id: int
    pipeline_run_id: int
    image_ref: str
    image_digest: Optional[str] = None
    platform: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None


class RunProvenanceResponse(BaseModel):
    run_id: int
    commands: list[CommandResponse]
    packages: list[PackageResponse]
    containers: list[ContainerResponse]


class PackageInventoryItem(BaseModel):
    manager: str
    name: str
    versions: list[str]
    pipelines: list[str]


class PackageInventoryResponse(BaseModel):
    packages: list[PackageInventoryItem]


class ContainerInventoryItem(BaseModel):
    image_ref: str
    digests: list[str]
    pipelines: list[str]


class ContainerInventoryResponse(BaseModel):
    containers: list[ContainerInventoryItem]
