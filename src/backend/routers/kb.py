from __future__ import annotations

from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from backend.crud import kb as kb_crud
from backend.database import get_db

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class ArticleCreate(BaseModel):
    title: str
    body: str
    category_id: Optional[str] = None
    tags: Optional[list[str]] = None
    status: str = "published"
    slug: Optional[str] = None


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    category_id: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None
    slug: Optional[str] = None


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------


@router.get("/categories")
async def list_categories(db: aiosqlite.Connection = Depends(get_db)):
    return await kb_crud.list_categories(db)


@router.post("/categories", status_code=201)
async def create_category(
    data: CategoryCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await kb_crud.create_category(db, **data.model_dump())


@router.put("/categories/{category_id}")
async def update_category(
    category_id: str,
    data: CategoryUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    result = await kb_crud.update_category(db, category_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")
    return result


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await kb_crud.delete_category(db, category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Article endpoints
# ---------------------------------------------------------------------------


@router.get("/articles")
async def list_articles(
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await kb_crud.list_articles(
        db,
        category_id=category,
        status=status,
        tag=tag,
        limit=limit,
        offset=offset,
    )


@router.post("/articles", status_code=201)
async def create_article(
    data: ArticleCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await kb_crud.create_article(db, **data.model_dump())


@router.get("/articles/{article_id}")
async def get_article(
    article_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    result = await kb_crud.get_article(db, article_id)
    if not result:
        raise HTTPException(status_code=404, detail="Article not found")
    return result


@router.put("/articles/{article_id}")
async def update_article(
    article_id: str,
    data: ArticleUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    result = await kb_crud.update_article(db, article_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Article not found")
    return result


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(
    article_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await kb_crud.delete_article(db, article_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Article not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_articles(
    q: str = Query(...),
    limit: int = Query(default=20, le=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    results = await kb_crud.search_articles(db, query=q, limit=limit)
    return {"results": results}
