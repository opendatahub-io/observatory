# Fix: chat session goes defunct on refresh / navigation / tab switch

## Context

Today a chat response only survives if the browser stays on the Chat page with the
SSE connection open for the entire generation. Two coupled defects cause the
"defunct session" bug:

1. **Backend — persistence is coupled to the client connection.** In
   `src/backend/routers/chat.py::send_message`, the assistant reply is written to
   the DB only at the *tail* of the `event_stream()` async generator that backs the
   `StreamingResponse`. When the client disconnects mid-stream (browser refresh,
   navigating to another route which unmounts `Chat`, or a tab/network drop),
   Starlette calls `aclose()` on that generator and raises `GeneratorExit` at a
   `yield`. The persistence block (lines ~161-185) never runs. The *user* message
   was already saved (line 85), so the conversation is left with a question and no
   answer — and the in-flight LLM work is thrown away.

2. **Frontend — all stream state is in-memory with no resume.** `Chat` is a route
   component (`src/frontend/src/App.tsx`); navigating away unmounts it and wipes
   `streamState`/`messages`. `useChatStream` never aborts the fetch on unmount, and
   there is no way to re-attach to an in-progress generation after remount/refresh.

**Desired outcome (user confirmed both):** a long analysis should *complete and
persist* even if you leave (set-and-forget), **and** returning to the conversation
(via navigation or refresh) should *re-attach to the live stream* and keep
rendering tokens when it is still running.

## Approach

Decouple generation from the request, and add a small in-memory pub/sub with
replay so any number of subscribers (the original POST, a reconnect after refresh,
a second tab) can follow one generation.

### Backend

**New module `src/backend/chat/stream_manager.py`** — an in-process registry of
active generations, keyed by `conversation_id`:

- `StreamSession`:
  - `buffer: list[str]` — every SSE string emitted so far (for replay to late joiners)
  - `subscribers: set[asyncio.Queue]` — live fan-out queues
  - `done: asyncio.Event`
  - `publish(sse)` — append to `buffer` and `put_nowait` to each subscriber (no
    `await`, so it is atomic vs. `subscribe`'s snapshot).
  - `finish()` — set `done`, push a sentinel to each subscriber.
  - `async subscribe()` — atomically snapshot `list(self.buffer)` and, if not done,
    add its queue to `subscribers` (no `await` between those two lines so no
    event is dropped or duplicated); yield the replay, then yield live events
    until sentinel; always discard its queue in `finally`.
- Module-level `_active: dict[str, StreamSession]` with `get/register/remove`, plus
  a `_pending_tasks: set[asyncio.Task]` to hold background-task references so they
  are not garbage-collected.

**Rewrite `send_message` in `src/backend/routers/chat.py`:**

- Keep validation + `await chat_crud.add_message(db, id, "user", content)`.
- If `_active.get(id)` already exists, return **409** (a generation is already
  running for this conversation; the client should attach, not start a second).
- Create a `StreamSession`, register it, and launch the generation as an
  independent `asyncio.create_task(_run_generation(...))` (added to
  `_pending_tasks`). The task body is the *current* event-building loop, but each
  `yield f"event: ...\n\n"` becomes `session.publish(...)`. Its `finally` does, in
  order: (a) persist the assistant message via `chat_crud.add_message(...)` and the
  auto-title via `update_conversation_title(...)` exactly as today, (b)
  `_active.remove(id)`, (c) `session.finish()`. Persist-before-remove guarantees a
  client that just missed the stream can still load the saved answer.
- Return `StreamingResponse(session.subscribe(), media_type="text/event-stream",
  headers=... same as today)`.

Because generation runs in its own task, a disconnecting subscriber only tears down
its `subscribe()` generator; the task keeps running and persists. Uses the global
singleton connection from `database.py::get_db` (already outlives requests — safe).

**New endpoint `GET /conversations/{id}/stream`:** if `_active.get(id)` exists,
return `StreamingResponse(session.subscribe(), ...)` (replays buffer, then live);
else return `Response(status_code=204)`. This is the reconnect path.

**App shutdown:** in `src/backend/app.py` lifespan, cancel any remaining
`_pending_tasks` on shutdown (best-effort) so tests/reloads don't leak tasks.

### Frontend

**`src/frontend/src/hooks/useChatStream.ts`:**
- Extract the reader/`processLine` block-building logic into a shared
  `consumeResponse(res, onComplete)` used by both entry points.
- `startStream(convId, content, onComplete)` — POST as today, then `consumeResponse`.
  If POST returns 409, fall back to `attachStream`.
- Add `attachStream(convId, onComplete)` — `GET /conversations/{id}/stream`; on 204
  return `false`; otherwise `consumeResponse` and return `true`.
- Keep the `AbortController` in `abortRef` and export `abort`; make abort tear down
  the client read **only** (backend keeps generating). On `AbortError`, do not call
  `onComplete`.

**`src/frontend/src/pages/Chat.tsx`:**
- Persist the active conversation across unmount/refresh with `localStorage`
  (`observatory.activeConvId`): set it in `loadConversation`/`createConversation`/
  new-chat/delete; read it on mount to auto-load + attempt `attachStream`.
- After `loadConversation(id)` loads persisted messages, call
  `attachStream(id, onComplete)`; if it attaches, drive the same streaming UI
  (`isStreaming`, `renderStreamingMessage`) already present.
- Add an unmount cleanup effect that calls `abort()` (frees the reader; backend
  still completes and persists).

This yields: leave mid-answer → generation finishes and is saved; come back or
refresh → `attachStream` replays what happened and continues live if still running,
or the persisted answer is already shown if it finished.

## Critical files

- `src/backend/chat/stream_manager.py` (new) — `StreamSession` + registry.
- `src/backend/routers/chat.py` — background-task generation, 409 guard, new
  `GET /stream` endpoint; reuse `backend.chat.agent.stream_chat_response` and
  `backend.crud.chat.{add_message,update_conversation_title,get_messages}`.
- `src/backend/app.py` — cancel pending tasks on shutdown.
- `src/frontend/src/hooks/useChatStream.ts` — shared consume, `attachStream`, abort.
- `src/frontend/src/pages/Chat.tsx` — localStorage active conv, attach-on-mount,
  abort-on-unmount.

## Verification

- **New backend tests** in `src/tests/test_chat_stream_resume.py` (monkeypatch
  `backend.chat.agent.stream_chat_response` with a controllable async generator so
  no real LLM is needed):
  1. *Persist-on-disconnect:* start the POST stream, consume one event, then close
     the client early; drive the fake generator to completion; assert
     `chat_crud.get_messages` now contains the assistant reply (proves the
     background task persisted independent of the client).
  2. *Attach/replay:* start a generation, then `GET /conversations/{id}/stream`
     and assert it replays prior events and receives `message_end`.
  3. *409:* a second POST while one is active returns 409.
  4. *204:* `GET /stream` for an idle conversation returns 204.
  Run: `PYTHONPATH=src .venv/bin/pytest -p no:cacheprovider -q src/tests/test_chat*.py`
- **Full suite + lint:** `PYTHONPATH=src .venv/bin/pytest -p no:cacheprovider -q`
  and `.venv/bin/ruff check src/backend` (expect all green — currently 387 passed).
- **Manual:** with `OBSERVATORY_ANTHROPIC_API_KEY` set, ask a question that triggers
  a long tool-using answer; mid-stream (a) navigate to another page and back — the
  answer should still be there/continue; (b) hard-refresh — the conversation
  reopens and re-attaches; (c) open the same conversation in a second tab while
  streaming — both render live.
- Frontend typecheck/build: `cd src/frontend && npm run build` (note: a pre-existing
  unrelated TS error in `Repositories.tsx` may remain).
