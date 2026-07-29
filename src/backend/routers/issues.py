from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from backend.crud import issues as issues_crud
from backend.crud.traces import search_trace_content
from backend.database import get_db

router = APIRouter(prefix="/api", tags=["issues"])


@router.get("/issues")
async def list_issues(
    search: Optional[str] = Query(default=None, description="Filter by Jira key substring"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Searchable list of Jira issue keys referenced in trace/artifact content,
    with aggregated run/pipeline stats."""
    return await issues_crud.list_issues(db, search=search, limit=limit, offset=offset)


@router.get("/issues/{jira_key}")
async def issue_detail(
    jira_key: str,
    limit: int = Query(default=100, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Run history and trace/artifact matches for a single Jira key."""
    return await search_trace_content(db, jira_key, limit=limit)


@router.post("/issues/refresh")
async def refresh_issue_index(db: aiosqlite.Connection = Depends(get_db)):
    """Rebuild the issue index from all trace/artifact content (operator action)."""
    return await issues_crud.rebuild_issue_index(db)
