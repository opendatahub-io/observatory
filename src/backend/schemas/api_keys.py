"""Pydantic models for scoped API key management."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str]
    expires_at: Optional[datetime] = None


class ApiKeyCreatedResponse(BaseModel):
    id: int
    key: str
    key_prefix: str
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: Optional[datetime] = None


class ApiKeyListItem(BaseModel):
    id: int
    key_prefix: str
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool
