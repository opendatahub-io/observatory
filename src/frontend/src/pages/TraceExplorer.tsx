import { useEffect, useState, useMemo, useCallback } from "react";
import { Link, useParams } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Span {
  id: number;
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  operation_name: string;
  service_name: string;
  start_time: string;
  end_time: string;
  duration_ms: number;
  status_code: string;
  attributes: string;
}

interface SpansResponse {
  spans: Span[];
}

interface SpanNode extends Span {
  depth: number;
}

interface TraceEvent {
  id: number;
  source: string;
  event_type: string;
  timestamp: string | null;
  content: string | null;
  line_number: number | null;
}

interface EventCount {
  event_type: string;
  source: string;
  cnt: number;
}

interface TracePackage {
  manager: string;
  name: string;
  version: string | null;
  arch: string | null;
  repo: string | null;
}

interface TraceSummary {
  event_counts: EventCount[];
  packages: TracePackage[];
  metadata: Record<string, string>;
}

interface LogFile {
  id: number;
  file_path: string;
  file_size: number | null;
}

type Tab = "job-trace" | "console-logs" | "otel-spans";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function formatDateTime(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
  } catch {
    return isoString;
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function buildSpanTree(spans: Span[]): SpanNode[] {
  const bySpanId = new Map<string, Span>();
  const childrenOf = new Map<string, Span[]>();

  for (const span of spans) bySpanId.set(span.span_id, span);

  const roots: Span[] = [];
  for (const span of spans) {
    if (span.parent_span_id == null || !bySpanId.has(span.parent_span_id)) {
      roots.push(span);
    } else {
      const siblings = childrenOf.get(span.parent_span_id) ?? [];
      siblings.push(span);
      childrenOf.set(span.parent_span_id, siblings);
    }
  }

  const byStartTime = (a: Span, b: Span) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime();

  roots.sort(byStartTime);
  for (const children of childrenOf.values()) children.sort(byStartTime);

  const result: SpanNode[] = [];
  function walk(span: Span, depth: number) {
    result.push({ ...span, depth });
    const children = childrenOf.get(span.span_id);
    if (children) for (const child of children) walk(child, depth + 1);
  }
  for (const root of roots) walk(root, 0);
  return result;
}

function parseAttributes(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function formatAxisLabel(ms: number): string {
  if (ms === 0) return "0";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

function tryPrettyJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  error: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  tool_call: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  command: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  section_start: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  section_end: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  package_install: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
};

const PAGE_SIZE = 50;

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function TraceExplorer() {
  const { runId } = useParams<{ runId: string }>();

  // Tab state
  const [activeTab, setActiveTab] = useState<Tab>("job-trace");

  // Job trace state
  const [summary, setSummary] = useState<TraceSummary | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [eventsPage, setEventsPage] = useState(0);
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [expandedEventId, setExpandedEventId] = useState<number | null>(null);

  // Console logs state
  const [logFiles, setLogFiles] = useState<LogFile[]>([]);
  const [selectedLogId, setSelectedLogId] = useState<number | null>(null);
  const [logContent, setLogContent] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);

  // OTEL spans state
  const [spans, setSpans] = useState<Span[]>([]);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  // Shared state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track which data sources have data
  const hasJobTrace = summary !== null && summary.event_counts.length > 0;
  const hasLogs = logFiles.length > 0;
  const hasSpans = spans.length > 0;

  /* ---- Initial data fetch ---- */
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;

    async function fetchAll() {
      setLoading(true);
      setError(null);

      try {
        const [sumRes, logsRes, spansRes] = await Promise.all([
          fetch(`/api/traces/runs/${encodeURIComponent(runId!)}/summary`),
          fetch(`/api/traces/runs/${encodeURIComponent(runId!)}/logs`),
          fetch(`/api/telemetry/spans/${encodeURIComponent(runId!)}`),
        ]);

        if (cancelled) return;

        let traceSummary: TraceSummary | null = null;
        let logs: LogFile[] = [];
        let otelSpans: Span[] = [];

        if (sumRes.ok) traceSummary = await sumRes.json();
        if (logsRes.ok) logs = await logsRes.json();
        if (spansRes.ok) {
          const data: SpansResponse = await spansRes.json();
          otelSpans = data.spans ?? [];
        }

        if (!cancelled) {
          setSummary(traceSummary);
          setLogFiles(logs);
          setSpans(otelSpans);

          if (traceSummary && traceSummary.event_counts.length > 0) {
            setActiveTab("job-trace");
          } else if (logs.length > 0) {
            setActiveTab("console-logs");
          } else if (otelSpans.length > 0) {
            setActiveTab("otel-spans");
          }

          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch trace data");
          setLoading(false);
        }
      }
    }

    void fetchAll();
    return () => { cancelled = true; };
  }, [runId]);

  /* ---- Fetch events when page/filter changes ---- */
  const fetchEvents = useCallback(async () => {
    if (!runId) return;
    const params = new URLSearchParams();
    if (eventTypeFilter) params.set("type", eventTypeFilter);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(eventsPage * PAGE_SIZE));

    try {
      const res = await fetch(`/api/traces/runs/${encodeURIComponent(runId)}/events?${params}`);
      if (res.ok) {
        const data = await res.json();
        setEvents(data.events ?? []);
        setEventsTotal(data.total ?? 0);
      }
    } catch { /* ignore */ }
  }, [runId, eventTypeFilter, eventsPage]);

  useEffect(() => {
    if (activeTab === "job-trace" && hasJobTrace) void fetchEvents();
  }, [activeTab, hasJobTrace, fetchEvents]);

  /* ---- Fetch selected log content ---- */
  useEffect(() => {
    if (selectedLogId === null) { setLogContent(null); return; }
    let cancelled = false;
    setLogLoading(true);

    fetch(`/api/artifacts/${selectedLogId}/content`)
      .then(res => res.ok ? res.text() : Promise.reject(`HTTP ${res.status}`))
      .then(text => { if (!cancelled) { setLogContent(text); setLogLoading(false); } })
      .catch(() => { if (!cancelled) { setLogContent("Failed to load log content."); setLogLoading(false); } });

    return () => { cancelled = true; };
  }, [selectedLogId]);

  /* ---- OTEL span helpers ---- */
  const spanNodes = useMemo(() => buildSpanTree(spans), [spans]);

  const { traceStart, traceDuration } = useMemo(() => {
    if (spans.length === 0) return { traceStart: 0, traceDuration: 0 };
    let earliest = Infinity;
    let latest = -Infinity;
    for (const span of spans) {
      const start = new Date(span.start_time).getTime();
      const end = new Date(span.end_time).getTime();
      if (start < earliest) earliest = start;
      if (end > latest) latest = end;
    }
    return { traceStart: earliest, traceDuration: Math.max(latest - earliest, 1) };
  }, [spans]);

  const selectedSpan = useMemo(() => {
    if (!selectedSpanId) return null;
    return spans.find((s) => s.span_id === selectedSpanId) ?? null;
  }, [spans, selectedSpanId]);

  const selectedAttributes = useMemo(() => {
    if (!selectedSpan) return {};
    return parseAttributes(selectedSpan.attributes);
  }, [selectedSpan]);

  const axisLabels = useMemo(() => {
    const count = 5;
    const labels: string[] = [];
    for (let i = 0; i <= count; i++) labels.push(formatAxisLabel((traceDuration / count) * i));
    return labels;
  }, [traceDuration]);

  /* ---- Tab button helper ---- */
  const tabBtn = (tab: Tab, label: string, count?: number) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
        activeTab === tab
          ? "border-primary-600 text-primary-600 dark:text-primary-400"
          : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700"
      }`}
    >
      {label}
      {count !== undefined && count > 0 && (
        <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">({count})</span>
      )}
    </button>
  );

  /* ---- Status helpers for OTEL spans ---- */
  function statusBarClass(code: string): string {
    switch (code.toUpperCase()) {
      case "OK": return "bg-emerald-400 dark:bg-emerald-500";
      case "ERROR": return "bg-red-400 dark:bg-red-500";
      default: return "bg-gray-300 dark:bg-gray-500";
    }
  }

  function statusBadgeClass(code: string): string {
    switch (code.toUpperCase()) {
      case "OK": return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
      case "ERROR": return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
      default: return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
    }
  }

  /* ---- Pagination helpers ---- */
  const totalPages = Math.max(1, Math.ceil(eventsTotal / PAGE_SIZE));

  /* ---- Aggregate event counts by type ---- */
  const eventCountsByType = useMemo(() => {
    if (!summary) return [];
    const byType = new Map<string, number>();
    for (const ec of summary.event_counts) {
      byType.set(ec.event_type, (byType.get(ec.event_type) ?? 0) + ec.cnt);
    }
    return Array.from(byType.entries())
      .map(([type, cnt]) => ({ type, cnt }))
      .sort((a, b) => b.cnt - a.cnt);
  }, [summary]);

  const totalEventCount = eventCountsByType.reduce((s, e) => s + e.cnt, 0);

  /* ---- Loading ---- */
  if (loading) {
    return (
      <div>
        <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Status Board
        </Link>
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading trace data...</div>
      </div>
    );
  }

  /* ---- Error ---- */
  if (error) {
    return (
      <div>
        <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Status Board
        </Link>
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <div className="font-semibold mb-1">Error loading traces</div>
          <div className="text-sm">{error}</div>
        </div>
      </div>
    );
  }

  /* ---- Empty ---- */
  if (!hasJobTrace && !hasLogs && !hasSpans) {
    return (
      <div>
        <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Status Board
        </Link>
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Trace Explorer</h1>
        </div>
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          No trace data available for this run.
        </div>
      </div>
    );
  }

  /* ---- Render ---- */
  return (
    <div>
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
        &larr; Back to Status Board
      </Link>

      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Trace Explorer</h1>
        <span className="text-sm text-gray-500 dark:text-gray-400">Run {runId}</span>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        {tabBtn("job-trace", "Job Trace", totalEventCount)}
        {tabBtn("console-logs", "Console Logs", logFiles.length)}
        {tabBtn("otel-spans", "OTEL Spans", spans.length)}
      </div>

      {/* ============================================= */}
      {/*  JOB TRACE TAB                                */}
      {/* ============================================= */}
      {activeTab === "job-trace" && (
        <div>
          {!hasJobTrace ? (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              No parsed trace events for this run.
            </div>
          ) : (
            <>
              {/* Metadata card */}
              {summary && Object.keys(summary.metadata).length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 mb-6">
                  <div className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">Metadata</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {Object.entries(summary.metadata).map(([key, value]) => (
                      <div key={key}>
                        <div className="text-xs text-gray-500 dark:text-gray-400">{key.replace(/_/g, " ")}</div>
                        <div className="text-sm text-gray-900 dark:text-gray-100 font-mono break-all">{value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Event counts */}
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-6">
                <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Events by Type &middot; {totalEventCount.toLocaleString()} total
                  </span>
                </div>
                {eventCountsByType.map((t) => {
                  const maxCount = eventCountsByType[0]?.cnt ?? 1;
                  return (
                    <div key={t.type} className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer"
                      onClick={() => { setEventTypeFilter(eventTypeFilter === t.type ? "" : t.type); setEventsPage(0); }}
                    >
                      <div className="flex justify-between items-center mb-1">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${EVENT_TYPE_COLORS[t.type] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                          {t.type}
                        </span>
                        <span className="text-xs text-gray-500 dark:text-gray-400">{t.cnt.toLocaleString()}</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div className="h-full bg-primary-400 dark:bg-primary-500 rounded-full" style={{ width: `${(t.cnt / maxCount) * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Events table */}
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-6">
                <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between flex-wrap gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Events {eventTypeFilter && <span className="text-primary-600 dark:text-primary-400">({eventTypeFilter})</span>}
                  </span>
                  <div className="flex items-center gap-2">
                    {eventTypeFilter && (
                      <button
                        onClick={() => { setEventTypeFilter(""); setEventsPage(0); }}
                        className="text-xs text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        Clear filter
                      </button>
                    )}
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {eventsTotal.toLocaleString()} event{eventsTotal !== 1 ? "s" : ""}
                    </span>
                  </div>
                </div>

                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-28">Type</th>
                      <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Content</th>
                      <th className="text-right px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-16">Line</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((ev) => (
                      <>
                        <tr
                          key={ev.id}
                          className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 ${expandedEventId === ev.id ? "bg-primary-50 dark:bg-primary-900/20" : ""}`}
                          onClick={() => setExpandedEventId(expandedEventId === ev.id ? null : ev.id)}
                        >
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800">
                            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${EVENT_TYPE_COLORS[ev.event_type] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                              {ev.event_type}
                            </span>
                          </td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs truncate max-w-0">
                            {ev.content ? ev.content.slice(0, 120) : "—"}
                          </td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-right text-xs text-gray-500 dark:text-gray-400 font-mono">
                            {ev.line_number ?? "—"}
                          </td>
                        </tr>
                        {expandedEventId === ev.id && (
                          <tr key={`${ev.id}-detail`}>
                            <td colSpan={3} className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                              <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-all max-h-96 overflow-auto">
                                {ev.content ? tryPrettyJson(ev.content) : "No content"}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </>
                    ))}
                    {events.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                          No events found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700">
                    <button
                      onClick={() => setEventsPage(Math.max(0, eventsPage - 1))}
                      disabled={eventsPage === 0}
                      className="text-xs text-primary-600 dark:text-primary-400 hover:underline disabled:opacity-40 disabled:no-underline"
                    >
                      Previous
                    </button>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Page {eventsPage + 1} of {totalPages}
                    </span>
                    <button
                      onClick={() => setEventsPage(Math.min(totalPages - 1, eventsPage + 1))}
                      disabled={eventsPage >= totalPages - 1}
                      className="text-xs text-primary-600 dark:text-primary-400 hover:underline disabled:opacity-40 disabled:no-underline"
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>

              {/* Packages table */}
              {summary && summary.packages.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
                    <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Packages &middot; {summary.packages.length.toLocaleString()}
                    </span>
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-20">Manager</th>
                        <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Name</th>
                        <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Version</th>
                        <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Arch</th>
                        <th className="text-left px-4 py-2 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Repo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.packages.map((pkg, i) => (
                        <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800">
                            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${EVENT_TYPE_COLORS["package_install"] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                              {pkg.manager}
                            </span>
                          </td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">{pkg.name}</td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-xs">{pkg.version ?? "—"}</td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-xs">{pkg.arch ?? "—"}</td>
                          <td className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-xs">{pkg.repo ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ============================================= */}
      {/*  CONSOLE LOGS TAB                             */}
      {/* ============================================= */}
      {activeTab === "console-logs" && (
        <div>
          {!hasLogs ? (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              No console logs available for this run.
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
              {/* Log file list */}
              <div className="lg:col-span-1">
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
                    <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Log Files ({logFiles.length})
                    </span>
                  </div>
                  {logFiles.map((lf) => (
                    <div
                      key={lf.id}
                      className={`px-4 py-3 border-b border-gray-100 dark:border-gray-800 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 ${
                        selectedLogId === lf.id ? "bg-primary-50 dark:bg-primary-900/20" : ""
                      }`}
                      onClick={() => setSelectedLogId(selectedLogId === lf.id ? null : lf.id)}
                    >
                      <div className="text-sm text-gray-900 dark:text-gray-100 font-mono break-all">{lf.file_path}</div>
                      {lf.file_size != null && (
                        <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{formatBytes(lf.file_size)}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Log content viewer */}
              <div className="lg:col-span-3">
                {selectedLogId === null ? (
                  <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                    Select a log file to view its contents.
                  </div>
                ) : logLoading ? (
                  <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading log...</div>
                ) : (
                  <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                    <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 font-mono">
                        {logFiles.find(f => f.id === selectedLogId)?.file_path}
                      </span>
                      <button
                        onClick={() => setSelectedLogId(null)}
                        className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
                      >
                        Close
                      </button>
                    </div>
                    <pre className="p-4 text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-all overflow-auto max-h-[70vh]">
                      {logContent}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ============================================= */}
      {/*  OTEL SPANS TAB                               */}
      {/* ============================================= */}
      {activeTab === "otel-spans" && (
        <div>
          {!hasSpans ? (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              No OTEL span data available for this run.
            </div>
          ) : (
            <>
              <div className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                {spans.length} span{spans.length !== 1 ? "s" : ""}
              </div>

              {/* Waterfall chart */}
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                <div className="flex items-center px-4 py-2 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <span className="w-[260px] min-w-[260px] flex-shrink-0">Operation</span>
                  <span className="w-[80px] min-w-[80px] flex-shrink-0 text-right">Duration</span>
                  <span className="flex-1 pl-4">Timeline</span>
                </div>

                {spanNodes.map((node) => {
                  const startOffset = new Date(node.start_time).getTime() - traceStart;
                  const leftPct = (startOffset / traceDuration) * 100;
                  const widthPct = (node.duration_ms / traceDuration) * 100;
                  const isSelected = selectedSpanId === node.span_id;

                  return (
                    <div
                      key={node.span_id}
                      className={`flex items-center px-4 py-1.5 border-b border-gray-100 dark:border-gray-800 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors ${isSelected ? "bg-primary-50 dark:bg-primary-900/20 hover:bg-primary-50 dark:hover:bg-primary-900/20" : ""}`}
                      onClick={() => setSelectedSpanId(isSelected ? null : node.span_id)}
                    >
                      <div className="w-[260px] min-w-[260px] flex-shrink-0 flex items-center overflow-hidden">
                        <span style={{ display: "inline-block", width: node.depth * 16, minWidth: node.depth * 16, flexShrink: 0 }} />
                        <span className="text-sm text-gray-900 dark:text-gray-100 truncate" title={`${node.operation_name} (${node.service_name})`}>
                          {node.operation_name}
                        </span>
                      </div>
                      <span className="w-[80px] min-w-[80px] flex-shrink-0 text-right text-xs text-gray-500 dark:text-gray-400 font-mono">
                        {formatDurationMs(node.duration_ms)}
                      </span>
                      <div className="flex-1 pl-4 relative h-5">
                        <div
                          className={`absolute top-0.5 h-4 rounded ${statusBarClass(node.status_code)}`}
                          style={{ left: `${leftPct}%`, width: `${Math.max(widthPct, 0.3)}%` }}
                          title={`${node.operation_name}: ${formatDurationMs(node.duration_ms)}`}
                        />
                      </div>
                    </div>
                  );
                })}

                <div className="flex justify-between px-4 py-2 text-[10px] text-gray-400 dark:text-gray-500 pl-[352px]">
                  {axisLabels.map((label, i) => (
                    <span key={i}>{label}</span>
                  ))}
                </div>
              </div>

              {/* Span detail panel */}
              {selectedSpan && (
                <div className="mt-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
                    <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{selectedSpan.operation_name}</span>
                    <button className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 cursor-pointer bg-transparent border-none" onClick={() => setSelectedSpanId(null)}>
                      Close
                    </button>
                  </div>
                  <div className="p-4">
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Service</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{selectedSpan.service_name}</span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Status</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                          <span className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full ${statusBadgeClass(selectedSpan.status_code)}`}>
                            {selectedSpan.status_code}
                          </span>
                        </span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Duration</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{formatDurationMs(selectedSpan.duration_ms)}</span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Start Time</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{formatDateTime(selectedSpan.start_time)}</span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">End Time</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{formatDateTime(selectedSpan.end_time)}</span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Trace ID</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{selectedSpan.trace_id}</span>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Span ID</span>
                        <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{selectedSpan.span_id}</span>
                      </div>
                      {selectedSpan.parent_span_id && (
                        <div>
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Parent Span ID</span>
                          <span className="text-sm text-gray-900 dark:text-gray-100 break-all">{selectedSpan.parent_span_id}</span>
                        </div>
                      )}
                    </div>

                    {Object.keys(selectedAttributes).length > 0 && (
                      <div className="mt-4">
                        <div className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-2">Attributes</div>
                        <table className="w-full text-sm">
                          <thead>
                            <tr>
                              <th className="text-left px-3 py-2 font-medium text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">Key</th>
                              <th className="text-left px-3 py-2 font-medium text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">Value</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(selectedAttributes).map(([key, value]) => (
                              <tr key={key}>
                                <td className="px-3 py-2 border-b border-gray-100 dark:border-gray-800 font-mono text-xs text-gray-600 dark:text-gray-400">{key}</td>
                                <td className="px-3 py-2 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-900 dark:text-gray-100 break-all">
                                  {typeof value === "string" ? value : JSON.stringify(value)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default TraceExplorer;
