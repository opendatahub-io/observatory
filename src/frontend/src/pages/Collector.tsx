import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { Link } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CollectorStatus {
  pipeline_id: number;
  pipeline_slug: string;
  pipeline_name: string;
  last_collected_at: string | null;
  last_run_external_id: string | null;
  last_error: string | null;
  consecutive_failures: number;
}

interface LogEntry {
  timestamp: number;
  level: string;
  logger: string;
  message: string;
}

type LogLevel = "ALL" | "DEBUG" | "INFO" | "WARNING" | "ERROR";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Convert an ISO timestamp to a human-readable "X ago" string. */
function timeAgo(dateString: string): string {
  const now = Date.now();
  const then = new Date(dateString).getTime();

  if (isNaN(then)) return "Invalid date";

  const diffMs = now - then;
  if (diffMs < 0) return "Just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return seconds <= 1 ? "Just now" : `${seconds} seconds ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return days === 1 ? "1 day ago" : `${days} days ago`;

  const months = Math.floor(days / 30);
  return months === 1 ? "1 month ago" : `${months} months ago`;
}

type StatusLevel = "green" | "yellow" | "red" | "grey";

/**
 * Determine the status indicator for a pipeline's collector:
 *  - "red"    if consecutive_failures > 0
 *  - "green"  if no errors and collected within the last 2 hours
 *  - "yellow" if no errors but stale (> 2 hours since last collection)
 *  - "grey"   if never collected
 */
function getStatusLevel(
  entry: CollectorStatus,
): StatusLevel {
  if (entry.consecutive_failures > 0) return "red";
  if (!entry.last_collected_at) return "grey";

  const ageMs = Date.now() - new Date(entry.last_collected_at).getTime();
  const twoHours = 2 * 60 * 60 * 1000;
  return ageMs <= twoHours ? "green" : "yellow";
}

const STATUS_LABELS: Record<StatusLevel, string> = {
  green: "Healthy",
  yellow: "Stale",
  red: "Failing",
  grey: "Never collected",
};

const DOT_CLASSES: Record<StatusLevel, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
  grey: "bg-gray-400",
};

function logLevelColor(level: string): string {
  switch (level) {
    case "DEBUG":
      return "text-slate-400";
    case "INFO":
      return "text-blue-400";
    case "WARNING":
      return "text-amber-400";
    case "ERROR":
      return "text-red-400";
    default:
      return "text-slate-400";
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const AUTO_REFRESH_INTERVAL_MS = 30_000; // 30 seconds

function Collector() {
  /* ---------- Collector status state ---------- */
  const [data, setData] = useState<CollectorStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triggerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ---------- Collector Logs state ---------- */
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [logLevelFilter, setLogLevelFilter] = useState<LogLevel>("ALL");
  const [logSearch, setLogSearch] = useState("");
  const [logLiveTail, setLogLiveTail] = useState(false);
  const [logAutoScroll, setLogAutoScroll] = useState(true);
  const logViewerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  /* ================================================================ */
  /*  Fetch functions                                                  */
  /* ================================================================ */

  /* ---------- Fetch collector status ---------- */

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUnavailable(false);

    try {
      const res = await fetch("/api/collector/status");
      if (!res.ok) {
        if (res.status === 404 || res.status === 502 || res.status === 503) {
          setUnavailable(true);
        } else {
          setError(`API returned ${res.status}: ${res.statusText}`);
        }
        return;
      }
      const json: CollectorStatus[] = await res.json();
      setData(json);
    } catch {
      // Network error, CORS, or server not running
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  }, []);

  /* ---------- Fetch collector logs ---------- */

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/logs");
      if (res.ok) {
        const json: LogEntry[] = await res.json();
        setLogEntries(json);
      }
    } catch {
      // Silently ignore
    }
  }, []);

  /* ================================================================ */
  /*  Effects                                                          */
  /* ================================================================ */

  /* ---------- Initial fetch ---------- */

  useEffect(() => {
    void fetchStatus();
    void fetchLogs();
  }, [fetchStatus, fetchLogs]);

  /* ---------- Auto-refresh ---------- */

  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(() => {
        void fetchStatus();
      }, AUTO_REFRESH_INTERVAL_MS);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [autoRefresh, fetchStatus]);

  /* ---------- Cleanup ---------- */

  useEffect(() => {
    return () => {
      if (triggerTimerRef.current) clearTimeout(triggerTimerRef.current);
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  /* ---------- Live tail SSE ---------- */

  useEffect(() => {
    if (logLiveTail) {
      const es = new EventSource("/api/admin/logs/stream");
      eventSourceRef.current = es;
      es.onmessage = (event) => {
        try {
          const entry: LogEntry = JSON.parse(event.data);
          setLogEntries((prev) => [...prev, entry]);
        } catch {
          // Ignore malformed events
        }
      };
      return () => {
        es.close();
        eventSourceRef.current = null;
      };
    } else {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    }
  }, [logLiveTail]);

  /* ---------- Auto-scroll log viewer ---------- */

  useEffect(() => {
    if (logAutoScroll && logLiveTail && logViewerRef.current) {
      logViewerRef.current.scrollTop = logViewerRef.current.scrollHeight;
    }
  }, [logEntries, logAutoScroll, logLiveTail]);

  /* ================================================================ */
  /*  Actions                                                          */
  /* ================================================================ */

  /* ---------- Manual trigger ---------- */

  const triggerCollector = async () => {
    setTriggerMsg(null);
    try {
      const res = await fetch("/api/collector/run", { method: "POST" });
      if (res.status === 202 || res.ok) {
        setTriggerMsg("Triggered");
      } else {
        setTriggerMsg(`Failed (${res.status})`);
      }
    } catch {
      setTriggerMsg("Failed (network error)");
    }

    // Clear the message after 3 seconds
    if (triggerTimerRef.current) clearTimeout(triggerTimerRef.current);
    triggerTimerRef.current = setTimeout(() => setTriggerMsg(null), 3000);
  };

  /* ---------- Log helpers ---------- */

  const filteredLogs = useMemo(() => {
    let entries = logEntries;
    if (logLevelFilter !== "ALL") {
      entries = entries.filter((e) => e.level === logLevelFilter);
    }
    if (logSearch) {
      const q = logSearch.toLowerCase();
      entries = entries.filter((e) => e.message.toLowerCase().includes(q));
    }
    return entries;
  }, [logEntries, logLevelFilter, logSearch]);

  const formatLogTimestamp = (ts: number): string => {
    const d = new Date(ts * 1000);
    const h = d.getHours().toString().padStart(2, "0");
    const m = d.getMinutes().toString().padStart(2, "0");
    const s = d.getSeconds().toString().padStart(2, "0");
    const ms = d.getMilliseconds().toString().padStart(3, "0");
    return `${h}:${m}:${s}.${ms}`;
  };

  const truncateLogger = (name: string): string => {
    // Remove "backend." prefix for brevity
    return name.replace(/^backend\./, "");
  };

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div>
      {/* ============================================================ */}
      {/* Header                                                        */}
      {/* ============================================================ */}
      <div className="flex justify-between items-start mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Collector</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh
          </label>
          <button
            className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer"
            onClick={() => void fetchStatus()}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button
            className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer bg-primary-600 text-white border-primary-600 hover:bg-primary-700"
            onClick={() => void triggerCollector()}
          >
            Run Collector Now
          </button>
          {triggerMsg && (
            <span className="text-sm text-emerald-600 dark:text-emerald-400 font-medium">{triggerMsg}</span>
          )}
        </div>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Collector health and status for each monitored pipeline.
      </p>

      {/* Loading state (initial load only) */}
      {loading && data.length === 0 && !unavailable && !error && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading collector status...</div>
      )}

      {/* API unavailable */}
      {unavailable && (
        <div className="text-center p-8 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-xl border border-amber-200 dark:border-amber-800">
          <p className="font-semibold mb-1">
            Collector status unavailable
          </p>
          <p className="text-sm">
            The collector status API is not reachable. It may still be starting
            up or has not been deployed yet.
          </p>
          <button
            className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer"
            onClick={() => void fetchStatus()}
            style={{ marginTop: 12 }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load collector status</p>
          <p className="text-sm">{error}</p>
          <button
            className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer"
            onClick={() => void fetchStatus()}
            style={{ marginTop: 12, borderColor: "#fecaca", color: "#dc2626" }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && !unavailable && data.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          No pipelines are registered for collection.
        </div>
      )}

      {/* Data table */}
      {data.length > 0 && (
        <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-6">
          <thead>
            <tr>
              <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Status</th>
              <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Pipeline</th>
              <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Last Collected</th>
              <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Last Error</th>
              <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Failures</th>
            </tr>
          </thead>
          <tbody>
            {data.map((entry) => {
              const level = getStatusLevel(entry);

              return (
                <tr key={entry.pipeline_id}>
                  {/* Status dot */}
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${DOT_CLASSES[level]}`}
                        title={STATUS_LABELS[level]}
                      />
                      <span>{STATUS_LABELS[level]}</span>
                    </div>
                  </td>

                  {/* Pipeline name */}
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <Link to={`/pipelines/${encodeURIComponent(entry.pipeline_slug)}`}>
                      {entry.pipeline_name}
                    </Link>
                  </td>

                  {/* Last collected */}
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    {entry.last_collected_at
                      ? timeAgo(entry.last_collected_at)
                      : "Never"}
                  </td>

                  {/* Last error */}
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    {entry.last_error ? (
                      <span
                        className="text-red-600 dark:text-red-400 text-xs truncate max-w-[300px] cursor-pointer hover:underline"
                        title={entry.last_error}
                        onClick={() => setExpandedError(entry.last_error)}
                      >
                        {entry.last_error}
                      </span>
                    ) : (
                      <span className="text-gray-400 dark:text-gray-500">None</span>
                    )}
                  </td>

                  {/* Consecutive failures */}
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <span
                      className={`font-mono ${
                        entry.consecutive_failures > 0
                          ? "text-red-600 dark:text-red-400 font-bold"
                          : ""
                      }`}
                    >
                      {entry.consecutive_failures}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Error detail modal */}
      {expandedError && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => setExpandedError(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full mx-4 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Error Details</div>
            <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap mb-4 max-h-64 overflow-y-auto">{expandedError}</div>
            <button
              className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => setExpandedError(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* ============================================================ */}
      {/* Collector Logs                                                */}
      {/* ============================================================ */}
      <div className="mt-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Collector Logs</h2>
        </div>

        <div className="flex gap-2 flex-wrap items-center mb-3">
          {(["ALL", "DEBUG", "INFO", "WARNING", "ERROR"] as LogLevel[]).map((level) => (
            <button
              key={level}
              className={`text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all ${logLevelFilter === level ? "bg-primary-600 text-white border-primary-600" : ""}`}
              onClick={() => setLogLevelFilter(level)}
            >
              {level}
            </button>
          ))}

          <input
            type="text"
            className="text-xs px-2.5 py-1 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 min-w-[140px]"
            placeholder="Search messages..."
            value={logSearch}
            onChange={(e) => setLogSearch(e.target.value)}
          />

          <button
            className={`text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 cursor-pointer transition-all ${logLiveTail ? "bg-emerald-600 text-white border-emerald-600" : ""}`}
            onClick={() => setLogLiveTail((v) => !v)}
          >
            {logLiveTail ? "Live: ON" : "Live: OFF"}
          </button>

          {logLiveTail && (
            <button
              className={`text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 cursor-pointer transition-all ${logAutoScroll ? "bg-emerald-600 text-white border-emerald-600" : ""}`}
              onClick={() => setLogAutoScroll((v) => !v)}
            >
              {logAutoScroll ? "Auto-scroll: ON" : "Auto-scroll: OFF"}
            </button>
          )}

          <button
            className="text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all"
            onClick={() => setLogEntries([])}
          >
            Clear
          </button>
        </div>

        <div className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs max-h-96 overflow-y-auto" ref={logViewerRef}>
          {filteredLogs.length === 0 ? (
            <div className="text-slate-500 text-center py-8">No log entries to display.</div>
          ) : (
            filteredLogs.map((entry, i) => (
              <div key={i} className="flex gap-2 py-0.5 hover:bg-slate-800/50">
                <span className="text-slate-500 flex-shrink-0">{formatLogTimestamp(entry.timestamp)}</span>
                <span className={`font-semibold flex-shrink-0 w-[60px] ${logLevelColor(entry.level)}`}>
                  {entry.level}
                </span>
                <span className="text-slate-500 flex-shrink-0 max-w-[120px] truncate" title={entry.logger}>
                  {truncateLogger(entry.logger)}
                </span>
                <span className="text-slate-200 break-all">{entry.message}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default Collector;
