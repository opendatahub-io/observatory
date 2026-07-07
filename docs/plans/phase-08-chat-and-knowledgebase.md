# Phase 8: Chat Interface & Knowledge Base

**Estimate:** 5-7 days
**Milestone:** M7-chat-kb

## Goal

Add two interconnected features to Observatory:

1. **Chat Interface** — a conversational UI where users can ask natural-language questions about any data in the system (pipelines, runs, claims, telemetry, vulnerabilities, etc.). An LLM agent answers by querying Observatory's own database and APIs.

2. **Knowledge Base** — a CRUD-managed collection of FAQs and reference articles that the chat agent can query and that users can browse directly. Operators populate it over time with institutional knowledge (common failure patterns, triage playbooks, architecture explanations). The agent can also propose new entries when it discovers recurring questions.

The two features share a common backend: the chat agent uses MCP tool calls to read/search the knowledge base alongside the existing Observatory data, giving it both live data and curated context.

---

## Architecture

### Chat Agent

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────────────┐
│  React UI   │──SSE──│  /api/v1/chat     │──────▶│  LLM (Claude API)   │
│  Chat panel │◀──────│  FastAPI router   │◀──────│  via Anthropic SDK  │
└─────────────┘       └──────────────────┘       └─────────────────────┘
                              │                            │
                              │                     MCP tool calls
                              ▼                            │
                      ┌──────────────┐              ┌──────▼──────┐
                      │  chat_*      │              │  Observatory │
                      │  DB tables   │              │  MCP Server  │
                      └──────────────┘              └─────────────┘
```

The FastAPI backend acts as the orchestrator:

1. Receives user message via POST `/api/v1/chat/messages`.
2. Builds a prompt with conversation history and available MCP tools.
3. Streams the LLM response back to the frontend via SSE.
4. When the LLM emits tool-use blocks, the backend executes them against Observatory's own data (SQL queries, knowledge base lookups) and feeds results back into the conversation.

### MCP Tool Surface

The chat agent has access to Observatory data through a set of MCP tools served by the backend itself (in-process, no separate server needed). Initial tool set:

| Tool | Description |
|------|-------------|
| `query_pipelines` | List/filter pipelines by status, group, platform |
| `query_runs` | Get recent runs, filter by pipeline/status/date range |
| `query_claims` | Search claims by text, type, verdict, source file |
| `query_telemetry` | Get cost/token summaries by model, skill, time range |
| `query_vulnerabilities` | Search CVEs by severity, package, container |
| `query_artifacts` | List/search job artifacts |
| `kb_search` | Full-text search over knowledge base articles |
| `kb_get` | Retrieve a specific KB article by ID or slug |
| `kb_suggest` | Propose a new KB article (requires operator approval) |

Tools return structured JSON. The LLM synthesizes answers from tool results. This keeps the LLM out of raw SQL and bounds what it can access.

### Knowledge Base

The knowledge base is a standalone CRUD resource that is also exposed as an MCP tool target.

```
┌─────────────┐       ┌──────────────────┐       ┌──────────────┐
│  React UI   │──REST─│  /api/v1/kb       │──────▶│  SQLite      │
│  KB browser │◀──────│  FastAPI router   │◀──────│  kb_* tables │
└─────────────┘       └──────────────────┘       └──────────────┘
```

**Data model:**

- **Categories** — top-level groupings (e.g., "Pipeline Failures", "Architecture", "Triage Playbooks")
- **Articles** — titled entries with markdown body, category, tags, and metadata
- **Suggested articles** — agent-proposed entries awaiting operator review

Users browse and manage KB articles through a dedicated UI page. The chat agent queries them via `kb_search` / `kb_get` MCP tools to ground answers in curated knowledge.

---

## Database Schema

### Chat Tables

```sql
CREATE TABLE chat_conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE chat_messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool_use', 'tool_result')),
    content         TEXT NOT NULL,
    metadata        TEXT,  -- JSON: model, tokens, tool calls, latency
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_chat_messages_conversation ON chat_messages(conversation_id, created_at);
```

### Knowledge Base Tables

```sql
CREATE TABLE kb_categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE kb_articles (
    id          TEXT PRIMARY KEY,
    category_id TEXT REFERENCES kb_categories(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    body        TEXT NOT NULL,           -- markdown
    tags        TEXT,                    -- JSON array
    status      TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'archived')),
    source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'agent_suggested', 'imported')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_kb_articles_category ON kb_articles(category_id);
CREATE INDEX idx_kb_articles_status ON kb_articles(status);
CREATE INDEX idx_kb_articles_slug ON kb_articles(slug);

-- SQLite FTS5 for full-text search
CREATE VIRTUAL TABLE kb_articles_fts USING fts5(
    title, body, tags,
    content='kb_articles',
    content_rowid='rowid'
);
```

---

## API Endpoints

### Chat

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/chat/conversations` | Create a new conversation |
| GET | `/api/v1/chat/conversations` | List conversations (recent first) |
| GET | `/api/v1/chat/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/v1/chat/conversations/{id}` | Delete conversation and messages |
| POST | `/api/v1/chat/conversations/{id}/messages` | Send message, returns SSE stream |

The message endpoint is the core interaction point. Request:

```json
{
  "content": "Which pipelines failed in the last 24 hours and what were the common errors?"
}
```

Response: SSE stream with events:

```
event: message_start
data: {"id": "msg_123", "role": "assistant"}

event: content_delta
data: {"text": "Let me check the recent pipeline runs..."}

event: tool_use
data: {"tool": "query_runs", "input": {"status": "failed", "since": "24h"}}

event: tool_result
data: {"tool": "query_runs", "result": [...]}

event: content_delta
data: {"text": "In the last 24 hours, 3 pipelines failed..."}

event: message_end
data: {"usage": {"input_tokens": 1200, "output_tokens": 450}}
```

### Knowledge Base

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/kb/categories` | List categories |
| POST | `/api/v1/kb/categories` | Create category |
| PUT | `/api/v1/kb/categories/{id}` | Update category |
| DELETE | `/api/v1/kb/categories/{id}` | Delete category |
| GET | `/api/v1/kb/articles` | List/search articles (query, category, status, tags) |
| POST | `/api/v1/kb/articles` | Create article |
| GET | `/api/v1/kb/articles/{id}` | Get article by ID or slug |
| PUT | `/api/v1/kb/articles/{id}` | Update article |
| DELETE | `/api/v1/kb/articles/{id}` | Delete article |
| GET | `/api/v1/kb/search?q=...` | Full-text search via FTS5 |

---

## Frontend

### Chat Page (`/chat`)

- Sidebar entry under a new **"Intelligence"** nav section
- Full-height chat panel with message history
- Streaming response display with typing indicator
- Tool-use visibility: collapsible sections showing what data the agent queried
- Conversation list in a left drawer (create new, switch, delete)
- Markdown rendering for agent responses (tables, code blocks, lists)
- Dark mode support consistent with existing UI

### Knowledge Base Page (`/knowledge-base`)

- Sidebar entry under **"Intelligence"** nav section (below Chat)
- Category-grouped article listing with search bar
- Article detail view with rendered markdown
- CRUD forms for creating/editing articles and categories
- Tag filtering
- Status badges (draft/published/archived)
- "Suggested by agent" indicator for agent-proposed articles with approve/reject actions

---

## Dependencies

Add to `pyproject.toml`:

```
anthropic>=0.52.0    # Claude API client with streaming + tool use
```

No additional frontend dependencies needed — existing React + Tailwind stack is sufficient. Markdown rendering can use a lightweight library if not already available, or render with `dangerouslySetInnerHTML` from a server-side conversion.

---

## Tasks

### Backend

- `task-chat-db-schema.md` — Add chat and KB tables to database.py
- `task-kb-crud.md` — KB router + CRUD operations + FTS5 search
- `task-mcp-tools.md` — Define MCP tool schemas and implement tool handlers against existing DB
- `task-chat-router.md` — Chat router with conversation CRUD and SSE streaming
- `task-chat-agent.md` — LLM orchestration: prompt construction, tool dispatch loop, streaming

### Frontend

- `task-chat-page.md` — Chat UI component with streaming display and conversation management
- `task-kb-page.md` — Knowledge base browser with CRUD forms and search
- `task-sidebar-nav.md` — Add Intelligence section to sidebar navigation

### Integration

- `task-kb-agent-suggest.md` — Agent-suggested articles workflow (propose → review → publish)
- `task-chat-context.md` — Prompt engineering: system prompt with Observatory context, tool descriptions

---

## Exit Criteria

- Users can open the chat, ask questions about pipeline data, and receive accurate streamed answers
- The agent uses MCP tools to query live Observatory data (not hallucinated answers)
- Tool calls are visible in the chat UI so users can verify what data was accessed
- Knowledge base supports full CRUD with categories, tags, search, and status management
- The chat agent queries the knowledge base when relevant and can suggest new articles
- Both features respect dark mode and match existing Observatory UI patterns
- Conversation history persists across page reloads
