"""Pydantic models for platform credential management."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CredentialCreate(BaseModel):
    name: str
    platform: str
    base_url: str
    token: str
    scopes: list[str] = ["*"]
    expires_at: Optional[datetime] = None


class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    token: Optional[str] = None
    scopes: Optional[list[str]] = None
    expires_at: Optional[datetime] = None


class CredentialListItem(BaseModel):
    id: int
    name: str
    platform: str
    base_url: str
    scopes: list[str]
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool


class CredentialTestResult(BaseModel):
    success: bool
    message: str
