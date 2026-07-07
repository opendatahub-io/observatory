from __future__ import annotations

from typing import Any, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from backend.crud import data_sources as ds_crud
from backend.database import get_db

router = APIRouter(prefix="/api/v1/data-sources", tags=["intelligence"])


class DataSourceCreate(BaseModel):
    name: str
    source_type: str
    endpoint: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    status: str = "active"


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    endpoint: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    status: Optional[str] = None


@router.get("")
async def list_data_sources(
    status: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await ds_crud.list_data_sources(db, status=status, source_type=source_type)


@router.post("", status_code=201)
async def create_data_source(
    data: DataSourceCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await ds_crud.create_data_source(
        db, **data.model_dump(),
    )


@router.get("/{source_id}")
async def get_data_source(
    source_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    source = await ds_crud.get_data_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    return source


@router.put("/{source_id}")
async def update_data_source(
    source_id: str,
    data: DataSourceUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    source = await ds_crud.update_data_source(
        db, source_id, **data.model_dump(exclude_unset=True),
    )
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_data_source(
    source_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await ds_crud.delete_data_source(db, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Data source not found")
    return Response(status_code=204)
