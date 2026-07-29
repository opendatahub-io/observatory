"""Tests for the authenticated query_jira chat tool.

Covers the auth behavior added when wiring the tool to a live Jira instance:
  - Jira Cloud (*.atlassian.net) uses Basic auth (email:token) against the
    current /rest/api/3/search/jql endpoint (the classic /search is 410 Gone).
  - Jira Server/Data Center uses a Bearer PAT against /rest/api/2/search.
  - Missing token → unauthenticated fallback with a note (no hard failure).
  - No endpoint configured → clear error pointing at .env.
  - The token is never echoed in surfaced error text.

The token is sourced from settings (.env), never from the data source.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from backend.chat import tools
from backend.database import get_db

# Bind the real client before any test monkeypatches httpx.AsyncClient — the tool
# module shares the global httpx module, so patching tools.httpx.AsyncClient also
# rebinds httpx.AsyncClient; the factory must call the original, not itself.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

ISSUE = {
    "key": "RHOAIENG-1",
    "fields": {
        "summary": "Fix the thing",
        "status": {"name": "New"},
        "issuetype": {"name": "Bug"},
        "priority": {"name": "Major"},
        "created": "2026-01-01T00:00:00.000+0000",
    },
}


@pytest.fixture
async def db(tmp_db):
    return await get_db()


def _set_settings(monkeypatch, *, url, email, token):
    import backend.config

    s = backend.config.settings
    monkeypatch.setattr(s, "jira_url", url)
    monkeypatch.setattr(s, "jira_email", email)
    monkeypatch.setattr(s, "jira_token", token)
    monkeypatch.setattr(s, "ssl_verify", True)


def _install_mock(monkeypatch, handler):
    """Route the tool's httpx.AsyncClient through a MockTransport."""

    def factory(*args, **kwargs):
        kwargs.pop("verify", None)  # ignored when a transport is supplied
        return _REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tools.httpx, "AsyncClient", factory)


def _make_handler(captured, *, issues=None, count=42, total=7):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path.endswith("/rest/api/3/search/jql"):
            return httpx.Response(200, json={"issues": issues or [], "isLast": True})
        if path.endswith("/rest/api/3/search/approximate-count"):
            return httpx.Response(200, json={"count": count})
        if "/rest/api/2/search" in path:
            return httpx.Response(200, json={"issues": issues or [], "total": total})
        return httpx.Response(404, json={"errorMessages": ["unexpected"]})

    return handler


@pytest.mark.anyio
async def test_cloud_uses_basic_auth_and_jql_endpoint(db, monkeypatch):
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="me@acme.com", token="SECRET")
    captured: list[httpx.Request] = []
    _install_mock(monkeypatch, _make_handler(captured, issues=[ISSUE], count=99))

    res = await tools._handle_query_jira(db, {"jql": "project = RHOAIENG", "max_results": 5})

    assert "error" not in res
    assert res["count"] == 1
    assert res["total"] == 99  # from approximate-count
    assert res["issues"][0]["key"] == "RHOAIENG-1"
    assert res["issues"][0]["status"] == "New"
    assert res["issues"][0]["issuetype"] == "Bug"

    search = [r for r in captured if r.url.path.endswith("/search/jql")][0]
    expected = "Basic " + base64.b64encode(b"me@acme.com:SECRET").decode()
    assert search.headers["Authorization"] == expected


@pytest.mark.anyio
async def test_server_uses_bearer_and_classic_search(db, monkeypatch):
    _set_settings(monkeypatch, url="https://jira.example.com", email="", token="PAT")
    captured: list[httpx.Request] = []
    _install_mock(monkeypatch, _make_handler(captured, issues=[ISSUE], total=3))

    res = await tools._handle_query_jira(db, {"jql": "project = Y"})

    assert "error" not in res
    assert res["total"] == 3  # server returns total directly
    req = [r for r in captured if "/rest/api/2/search" in str(r.url)][0]
    assert req.headers["Authorization"] == "Bearer PAT"


@pytest.mark.anyio
async def test_unauthenticated_fallback_when_no_token(db, monkeypatch):
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="me@acme.com", token="")
    captured: list[httpx.Request] = []
    _install_mock(monkeypatch, _make_handler(captured, issues=[ISSUE]))

    res = await tools._handle_query_jira(db, {"jql": "project = X"})

    assert "note" in res and "unauthenticated" in res["note"]
    search = [r for r in captured if "/search/jql" in str(r.url)][0]
    assert "Authorization" not in search.headers


@pytest.mark.anyio
async def test_error_when_not_configured(db, monkeypatch):
    _set_settings(monkeypatch, url="", email="", token="")
    res = await tools._handle_query_jira(db, {"jql": "project = Z"})
    assert "error" in res
    assert ".env" in res["error"]


@pytest.mark.anyio
async def test_cloud_basic_requires_email(db, monkeypatch):
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="", token="SECRET")
    res = await tools._handle_query_jira(db, {"jql": "project = X"})
    assert "error" in res
    assert "email" in res["error"].lower()


@pytest.mark.anyio
async def test_token_is_scrubbed_from_errors(db, monkeypatch):
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="me@acme.com", token="SUPERSECRET")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad credentials SUPERSECRET leaked")

    _install_mock(monkeypatch, handler)
    res = await tools._handle_query_jira(db, {"jql": "project = X"})

    assert "error" in res
    assert "SUPERSECRET" not in res["error"]
    assert "***" in res["error"]


@pytest.mark.anyio
async def test_requested_fields_are_returned_and_normalized(db, monkeypatch):
    """Requesting fields beyond the defaults returns them, with Jira's object /
    ADF shapes flattened to readable values."""
    rich_issue = {
        "key": "RHOAIENG-9",
        "fields": {
            "summary": "Rich issue",
            "labels": ["backend", "urgent"],
            "updated": "2026-02-02T10:00:00.000+0000",
            "assignee": {"displayName": "Ada Lovelace", "emailAddress": "ada@x.com"},
            "description": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "First line."}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "Second line."}]},
                ],
            },
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Grace Hopper"},
                        "created": "2026-02-01T00:00:00.000+0000",
                        "body": {
                            "type": "doc",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "Looks good."}]},
                            ],
                        },
                    }
                ]
            },
        },
    }
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="me@acme.com", token="SECRET")
    captured: list[httpx.Request] = []
    _install_mock(monkeypatch, _make_handler(captured, issues=[rich_issue], count=1))

    res = await tools._handle_query_jira(
        db,
        {
            "jql": "key = RHOAIENG-9",
            "fields": "key,summary,description,labels,updated,assignee,comment",
        },
    )

    assert "error" not in res
    issue = res["issues"][0]
    assert issue["key"] == "RHOAIENG-9"
    assert issue["summary"] == "Rich issue"
    assert issue["labels"] == ["backend", "urgent"]
    assert issue["updated"] == "2026-02-02T10:00:00.000+0000"
    assert issue["assignee"] == "Ada Lovelace"
    assert issue["description"] == "First line.\nSecond line."
    assert issue["comment"] == [
        {
            "author": "Grace Hopper",
            "created": "2026-02-01T00:00:00.000+0000",
            "updated": None,
            "body": "Looks good.",
        }
    ]

    # The requested fields must actually be forwarded to Jira.
    search = [r for r in captured if r.url.path.endswith("/search/jql")][0]
    assert "description" in search.url.params["fields"]
    assert "comment" in search.url.params["fields"]


@pytest.mark.anyio
async def test_data_source_endpoint_overrides_env_url(db, monkeypatch):
    """A Jira data-source row's endpoint takes precedence over settings.jira_url."""
    from backend.crud import data_sources as ds_crud

    await ds_crud.create_data_source(
        db, name="Jira", source_type="jira", endpoint="https://override.example.com",
    )
    _set_settings(monkeypatch, url="https://acme.atlassian.net", email="me@acme.com", token="PAT")
    captured: list[httpx.Request] = []
    _install_mock(monkeypatch, _make_handler(captured, issues=[ISSUE], total=1))

    res = await tools._handle_query_jira(db, {"jql": "project = X"})

    assert "error" not in res
    # override.example.com is not *.atlassian.net → classic /search + Bearer
    req = captured[0]
    assert str(req.url).startswith("https://override.example.com/rest/api/2/search")
    assert req.headers["Authorization"] == "Bearer PAT"
