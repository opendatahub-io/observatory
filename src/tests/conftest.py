import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)

    import backend.config
    backend.config.settings = backend.config.Settings(database_path=db_path)

    import backend.database
    backend.database._db = None

    from backend.database import connect, disconnect, init_schema
    db = await connect()
    await init_schema(db)
    yield db_path
    await disconnect()
    backend.database._db = None


@pytest.fixture
async def client(tmp_db):
    from backend.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
