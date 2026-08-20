import asyncio

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response

import backend.config
from backend import git_sync
from backend.database import get_db
from backend.crud.repositories import (
    list_repositories,
    get_repository,
    get_repository_by_triple,
    get_linked_pipelines,
    count_links,
    create_repository,
    update_repository,
    delete_repository,
    record_sync_result,
    list_tree,
    read_blob,
    search_files,
)
from backend.schemas.repositories import (
    RepositoryCreate,
    RepositoryUpdate,
    RepositoryResponse,
    RepositoryDetailResponse,
    SyncResult,
    TreeResponse,
    BlobResponse,
    SearchResponse,
)

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


@router.get("", response_model=list[RepositoryResponse])
async def list_repos(
    status: str | None = Query(None),
    kind: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await list_repositories(db, status=status, kind=kind)


@router.get("/lookup", response_model=RepositoryResponse)
async def lookup_repo(
    domain: str = Query(...),
    owner: str = Query(...),
    name: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Look up a repository by (domain, owner, name). ``owner`` may contain
    nested GitLab subgroup segments, hence query params rather than a path."""
    repo = await get_repository_by_triple(db, domain, owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.post("", response_model=RepositoryResponse, status_code=201)
async def register_repo(
    data: RepositoryCreate, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        return await create_repository(db, data.model_dump())
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Repository with this (domain, owner, name) already exists",
        )


@router.get("/{repo_id}", response_model=RepositoryDetailResponse)
async def get_repo(repo_id: int, db: aiosqlite.Connection = Depends(get_db)):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    repo["linked_pipelines"] = await get_linked_pipelines(db, repo_id)
    return repo


@router.put("/{repo_id}", response_model=RepositoryResponse)
async def edit_repo(
    repo_id: int, data: RepositoryUpdate, db: aiosqlite.Connection = Depends(get_db)
):
    repo = await update_repository(db, repo_id, data.model_dump(exclude_unset=True))
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.post("/{repo_id}/sync", response_model=SyncResult)
async def sync_repo(repo_id: int, db: aiosqlite.Connection = Depends(get_db)):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    result = await asyncio.to_thread(
        git_sync.sync_repository,
        repo["domain"],
        repo["owner"],
        repo["name"],
        backend.config.settings.checkout_root,
        repo["default_branch"],
        backend.config.settings.repo_sync_depth,
    )
    await record_sync_result(db, repo_id, result["status"], result.get("error"))
    return result


@router.delete("/{repo_id}", status_code=204)
async def deregister_repo(repo_id: int, db: aiosqlite.Connection = Depends(get_db)):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if await count_links(db, repo_id) > 0:
        raise HTTPException(
            status_code=409,
            detail="Repository is still linked to one or more pipelines; "
            "remove those references first",
        )
    await delete_repository(db, repo_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# File browsing
# ---------------------------------------------------------------------------

@router.get("/{repo_id}/tree", response_model=TreeResponse)
async def repo_tree(
    repo_id: int,
    path: str = Query(".", description="Relative path within the checkout"),
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        return await asyncio.to_thread(list_tree, repo, path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{repo_id}/blob", response_model=BlobResponse)
async def repo_blob(
    repo_id: int,
    path: str = Query(..., description="Relative file path within the checkout"),
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        return await asyncio.to_thread(read_blob, repo, path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IsADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{repo_id}/search", response_model=SearchResponse)
async def repo_search(
    repo_id: int,
    q: str = Query(..., description="Search pattern (passed to git grep)"),
    glob: str | None = Query(None, description="File glob filter, e.g. '*.py'"),
    db: aiosqlite.Connection = Depends(get_db),
):
    repo = await get_repository(db, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        return await asyncio.to_thread(search_files, repo, q, glob)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
