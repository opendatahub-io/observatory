# ADR-0007: Collector Log Viewing and Tailing in the Frontend

## Status

Accepted

## Context

The collector logs to container stdout via Python's `logging` module. To see what the collector is doing, operators must SSH into the pod or run `podman logs`. There's no visibility from the browser.

For a self-contained observability tool, the collector's own behavior should be observable from the tool itself.

## Decision

Add a ring buffer log store in the backend and a real-time log viewer in the Admin UI.

### Backend: Ring Buffer Log Store

Add a custom Python logging handler that captures collector log records into an in-memory ring buffer (last N entries, default 1000). No database — logs are ephemeral and high-volume.

```python
class RingBufferHandler(logging.Handler):
    def __init__(self, capacity=1000):
        super().__init__()
        self.buffer = collections.deque(maxlen=capacity)

    def emit(self, record):
        self.buffer.append({
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        })
```

Attach it to the `backend.collector` logger namespace so it captures all collector activity (scheduler, GitLab, GitHub, artifacts, parsers).

### Backend: API Endpoints

- `GET /api/admin/logs` — return the full buffer (last N entries), optionally filtered by `level` (INFO, WARNING, ERROR) and `since` (timestamp). Returns JSON array.
- `GET /api/admin/logs/stream` — SSE (Server-Sent Events) endpoint for real-time tailing. Each new log entry is pushed as an SSE event. Uses `asyncio.Queue` per connected client.

SSE is the right fit here — it's unidirectional (server → client), works through HTTP proxies/load balancers, and requires no WebSocket infrastructure. The client uses `EventSource` which auto-reconnects on disconnect.

### Frontend: Log Viewer in Admin

Add a "Collector Logs" section to the Admin page:

- **Log table**: timestamp, level (colored badge), logger name, message
- **Level filter**: buttons for All / INFO / WARNING / ERROR
- **Auto-scroll toggle**: when on, new entries appear at the bottom and auto-scroll
- **Live tail toggle**: connects to SSE endpoint, appends entries in real time
- **Pause/Resume**: stop auto-scroll without disconnecting SSE
- **Clear**: clear the displayed logs (not the server buffer)
- **Search**: text filter on message content

### Files

**New:**
- `src/backend/logging_handler.py` — RingBufferHandler + SSE queue management
- `src/backend/routers/logs.py` — GET /api/admin/logs + GET /api/admin/logs/stream

**Modify:**
- `src/backend/app.py` — attach handler to collector logger, register logs router
- `src/frontend/src/pages/Admin.tsx` — add Collector Logs section

### Why Not Database

Logs are high-volume (potentially hundreds per collector cycle), ephemeral (only recent history matters), and append-only. Writing them to SQLite would bloat the database and add write contention with the collector's actual data writes. An in-memory ring buffer is O(1) append, bounded memory, and zero I/O.

### Why Not WebSocket

SSE is simpler, works over HTTP/1.1, auto-reconnects natively, and we only need server→client push. WebSocket adds bidirectional complexity we don't need.

## Consequences

Positive:
- Operators can watch collector activity from the browser in real time
- No SSH/kubectl access needed to debug collection issues
- Bounded memory usage (fixed-size ring buffer)
- SSE auto-reconnects on network interruption

Negative:
- Logs lost on container restart (in-memory only) — acceptable for operational logs
- One more SSE connection per admin viewer — negligible resource cost
- Ring buffer size is a tradeoff: too small loses history, too large uses memory
