from typing import Any, Optional

from pydantic import BaseModel


class SBOMCreate(BaseModel):
    image_digest: str
    image_ref: str
    format: str = "spdx-json"
    sbom: dict[str, Any]
    generator: Optional[str] = None
    generated_at: Optional[str] = None


class SBOMListItem(BaseModel):
    id: int
    image_digest: str
    image_ref: str
    format: str
    generator: Optional[str] = None
    generated_at: Optional[str] = None
    created_at: Optional[str] = None


class SBOMDetail(BaseModel):
    id: int
    image_digest: str
    image_ref: str
    format: str
    sbom: dict[str, Any]
    generator: Optional[str] = None
    generated_at: Optional[str] = None
    created_at: Optional[str] = None


class VulnerabilityResponse(BaseModel):
    id: int
    sbom_id: int
    vuln_id: str
    package_name: Optional[str] = None
    installed_version: Optional[str] = None
    fixed_version: Optional[str] = None
    severity: Optional[str] = None
    scanned_at: Optional[str] = None


class VulnerabilitySummaryItem(BaseModel):
    vuln_id: str
    package_name: Optional[str] = None
    installed_version: Optional[str] = None
    fixed_version: Optional[str] = None
    severity: Optional[str] = None
    image_digest: str
    image_ref: str
    scanned_at: Optional[str] = None
