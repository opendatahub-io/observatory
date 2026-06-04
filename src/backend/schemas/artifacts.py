from typing import Optional

from pydantic import BaseModel


class ArtifactFileResponse(BaseModel):
    id: int
    source: str
    source_ref: Optional[str] = None
    file_path: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: Optional[str] = None


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactFileResponse]
    total: int
