import { useEffect, useState, useMemo } from "react";
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

/** Span augmented with tree depth for rendering. */
interface SpanNode extends Span {
  depth: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format duration in ms to a readable string. */
function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) {
    const secs = (ms / 1000).toFixed(1);
    return `${secs}s`;
  }
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

/** Format an ISO datetime string to a short readable format. */
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

/**
 * Build a flat list of spans ordered depth-first with depth annotations.
 * Roots are spans whose parent_span_id is null or whose parent is not in the list.
 */
function buildSpanTree(spans: Span[]): SpanNode[] {
  const bySpanId = new Map<string, Span>();
  const childrenOf = new Map<string, Span[]>();

  for (const span of spans) {
    bySpanId.set(span.span_id, span);
  }

  // Identify roots vs children
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

  // Sort roots and children by start_time
  const byStartTime = (a: Span, b: Span) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime();

  roots.sort(byStartTime);
  for (const children of childrenOf.values()) {
    children.sort(byStartTime);
  }

  // DFS traversal
  const result: SpanNode[] = [];
  function walk(span: Span, depth: number) {
    result.push({ ...span, depth });
    const children = childrenOf.get(span.span_id);
    if (children) {
      for (const child of children) {
        walk(child, depth + 1);
      }
    }
  }

  for (const root of roots) {
    walk(root, 0);
  }

  return result;
}

/** Parse the attributes JSON string into key-value pairs. */
function parseAttributes(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

/** Format a time axis label from ms offset. */
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

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function TraceExplorer() {
  const { runId } = useParams<{ runId: string }>();

  const [spans, setSpans] = useState<Span[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  /* Fetch spans on mount */
  useEffect(() => {
    if (!runId) return;

    let cancelled = false;

    async function fetchSpans() {
      setLoading(true);
      setError(null);

      try {
        const res = await fetch(
          `/api/telemetry/spans/${encodeURIComponent(runId!)}`
        );

        if (!res.ok) {
          if (!cancelled) {
            setError(`Server returned ${res.status}`);
            setLoading(false);
          }
          return;
        }

        const data: SpansResponse = await res.json();
        if (!cancelled) {
          setSpans(data.spans ?? []);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to fetch spans"
          );
          setLoading(false);
        }
      }
    }

    void fetchSpans();

    return () => {
      cancelled = true;
    };
  }, [runId]);

  /* Build the tree and compute timeline boundaries */
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

    return {
      traceStart: earliest,
      traceDuration: Math.max(latest - earliest, 1),
    };
  }, [spans]);

  const selectedSpan = useMemo(() => {
    if (!selectedSpanId) return null;
    return spans.find((s) => s.span_id === selectedSpanId) ?? null;
  }, [spans, selectedSpanId]);

  const selectedAttributes = useMemo(() => {
    if (!selectedSpan) return {};
    return parseAttributes(selectedSpan.attributes);
  }, [selectedSpan]);

  /* Generate time axis labels (5 evenly spaced marks) */
  const axisLabels = useMemo(() => {
    const count = 5;
    const labels: string[] = [];
    for (let i = 0; i <= count; i++) {
      labels.push(formatAxisLabel((traceDuration / count) * i));
    }
    return labels;
  }, [traceDuration]);

  /* ---------- Loading ---------- */
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

  /* ---------- Error ---------- */
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

  /* ---------- Empty ---------- */
  if (spans.length === 0) {
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

  /* ---------- Status helpers ---------- */
  function statusBarClass(code: string): string {
    switch (code.toUpperCase()) {
      case "OK":
        return "bg-emerald-400 dark:bg-emerald-500";
      case "ERROR":
        return "bg-red-400 dark:bg-red-500";
      default:
        return "bg-gray-300 dark:bg-gray-500";
    }
  }

  function statusBadgeClass(code: string): string {
    switch (code.toUpperCase()) {
      case "OK":
        return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
      case "ERROR":
        return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
      default:
        return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
    }
  }

  /* ---------- Render ---------- */
  return (
    <div>
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
        &larr; Back to Status Board
      </Link>

      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Trace Explorer</h1>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {spans.length} span{spans.length !== 1 ? "s" : ""} &middot; Run{" "}
          {runId}
        </span>
      </div>

      {/* Waterfall chart */}
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
        {/* Column header */}
        <div className="flex items-center px-4 py-2 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          <span className="w-[260px] min-w-[260px] flex-shrink-0">Operation</span>
          <span className="w-[80px] min-w-[80px] flex-shrink-0 text-right">Duration</span>
          <span className="flex-1 pl-4">Timeline</span>
        </div>

        {/* Span rows */}
        {spanNodes.map((node) => {
          const startOffset =
            new Date(node.start_time).getTime() - traceStart;
          const leftPct = (startOffset / traceDuration) * 100;
          const widthPct = (node.duration_ms / traceDuration) * 100;
          const isSelected = selectedSpanId === node.span_id;

          return (
            <div
              key={node.span_id}
              className={`flex items-center px-4 py-1.5 border-b border-gray-100 dark:border-gray-800 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors ${isSelected ? "bg-primary-50 dark:bg-primary-900/20 hover:bg-primary-50 dark:hover:bg-primary-900/20" : ""}`}
              onClick={() =>
                setSelectedSpanId(isSelected ? null : node.span_id)
              }
            >
              {/* Label with indentation */}
              <div className="w-[260px] min-w-[260px] flex-shrink-0 flex items-center overflow-hidden">
                <span
                  style={{
                    display: "inline-block",
                    width: node.depth * 16,
                    minWidth: node.depth * 16,
                    flexShrink: 0,
                  }}
                />
                <span
                  className="text-sm text-gray-900 dark:text-gray-100 truncate"
                  title={`${node.operation_name} (${node.service_name})`}
                >
                  {node.operation_name}
                </span>
              </div>

              {/* Duration */}
              <span className="w-[80px] min-w-[80px] flex-shrink-0 text-right text-xs text-gray-500 dark:text-gray-400 font-mono">
                {formatDurationMs(node.duration_ms)}
              </span>

              {/* Timeline bar */}
              <div className="flex-1 pl-4 relative h-5">
                <div
                  className={`absolute top-0.5 h-4 rounded ${statusBarClass(node.status_code)}`}
                  style={{
                    left: `${leftPct}%`,
                    width: `${Math.max(widthPct, 0.3)}%`,
                  }}
                  title={`${node.operation_name}: ${formatDurationMs(node.duration_ms)}`}
                />
              </div>
            </div>
          );
        })}

        {/* Time axis */}
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
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {selectedSpan.operation_name}
            </span>
            <button
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 cursor-pointer bg-transparent border-none"
              onClick={() => setSelectedSpanId(null)}
            >
              Close
            </button>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Service</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {selectedSpan.service_name}
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Status</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  <span
                    className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full ${statusBadgeClass(selectedSpan.status_code)}`}
                  >
                    {selectedSpan.status_code}
                  </span>
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Duration</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {formatDurationMs(selectedSpan.duration_ms)}
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Start Time</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {formatDateTime(selectedSpan.start_time)}
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">End Time</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {formatDateTime(selectedSpan.end_time)}
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Trace ID</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {selectedSpan.trace_id}
                </span>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Span ID</span>
                <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                  {selectedSpan.span_id}
                </span>
              </div>
              {selectedSpan.parent_span_id && (
                <div>
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-0.5">Parent Span ID</span>
                  <span className="text-sm text-gray-900 dark:text-gray-100 break-all">
                    {selectedSpan.parent_span_id}
                  </span>
                </div>
              )}
            </div>

            {/* Attributes table */}
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
                          {typeof value === "string"
                            ? value
                            : JSON.stringify(value)}
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
    </div>
  );
}

export default TraceExplorer;
