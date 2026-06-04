"""Tests for the ring-buffer log handler and /api/admin/logs endpoints."""

import logging
import time

import pytest


# ---------------------------------------------------------------------------
# Ring buffer unit tests
# ---------------------------------------------------------------------------


class TestRingBufferHandler:
    def test_captures_log_entries(self):
        from backend.logging_handler import RingBufferHandler

        handler = RingBufferHandler(capacity=100)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger("test.ring_buffer.capture")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            logger.info("hello world")

            entries = handler.get_entries()
            assert len(entries) == 1
            assert entries[0]["level"] == "INFO"
            assert entries[0]["logger"] == "test.ring_buffer.capture"
            assert entries[0]["message"] == "hello world"
            assert isinstance(entries[0]["timestamp"], float)
        finally:
            logger.removeHandler(handler)

    def test_level_filter(self):
        from backend.logging_handler import RingBufferHandler

        handler = RingBufferHandler(capacity=100)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger("test.ring_buffer.level_filter")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            logger.debug("debug msg")
            logger.info("info msg")
            logger.warning("warn msg")
            logger.error("error msg")

            assert len(handler.get_entries()) == 4
            assert len(handler.get_entries(level="INFO")) == 1
            assert handler.get_entries(level="INFO")[0]["message"] == "info msg"
            assert len(handler.get_entries(level="ERROR")) == 1
            assert len(handler.get_entries(level="DEBUG")) == 1
            assert len(handler.get_entries(level="WARNING")) == 1
        finally:
            logger.removeHandler(handler)

    def test_since_filter(self):
        from backend.logging_handler import RingBufferHandler

        handler = RingBufferHandler(capacity=100)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger("test.ring_buffer.since_filter")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            logger.info("old message")
            cutoff = time.time()
            # Small sleep to ensure timestamp difference
            time.sleep(0.01)
            logger.info("new message")

            entries = handler.get_entries(since=cutoff)
            assert len(entries) == 1
            assert entries[0]["message"] == "new message"
        finally:
            logger.removeHandler(handler)

    def test_capacity_is_bounded(self):
        from backend.logging_handler import RingBufferHandler

        handler = RingBufferHandler(capacity=10)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger("test.ring_buffer.capacity")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            for i in range(25):
                logger.info(f"message {i}")

            entries = handler.get_entries()
            assert len(entries) == 10
            # Oldest entries should have been evicted
            assert entries[0]["message"] == "message 15"
            assert entries[-1]["message"] == "message 24"
        finally:
            logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_logs_returns_entries(client):
    """GET /api/admin/logs returns captured log entries."""
    # Emit a log via the collector logger
    logger = logging.getLogger("backend.collector.test")
    logger.info("test log entry for API")

    resp = await client.get("/api/admin/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)

    # Find our test entry
    matching = [e for e in body if e["message"] == "test log entry for API"]
    assert len(matching) >= 1
    entry = matching[0]
    assert entry["level"] == "INFO"
    assert entry["logger"] == "backend.collector.test"


@pytest.mark.asyncio
async def test_get_logs_level_filter(client):
    """GET /api/admin/logs?level=ERROR filters by level."""
    logger = logging.getLogger("backend.collector.test_filter")
    logger.info("info msg for filter test")
    logger.error("error msg for filter test")

    resp = await client.get("/api/admin/logs?level=ERROR")
    assert resp.status_code == 200
    body = resp.json()

    # All returned entries should be ERROR level
    for entry in body:
        assert entry["level"] == "ERROR"

    # Our error message should be present
    matching = [e for e in body if e["message"] == "error msg for filter test"]
    assert len(matching) >= 1


@pytest.mark.asyncio
async def test_get_logs_since_filter(client):
    """GET /api/admin/logs?since=<ts> filters by timestamp."""
    logger = logging.getLogger("backend.collector.test_since")
    logger.info("old entry for since test")
    cutoff = time.time()
    time.sleep(0.01)
    logger.info("new entry for since test")

    resp = await client.get(f"/api/admin/logs?since={cutoff}")
    assert resp.status_code == 200
    body = resp.json()

    messages = [e["message"] for e in body]
    assert "new entry for since test" in messages
    assert "old entry for since test" not in messages
