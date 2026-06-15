import { useEffect, useState, useCallback } from "react";
import { X } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OtelLogSummary {
  total_logs: number;
  distinct_traces: number;
  recent_count: number;
  by_severity: { severity_text: string; cnt: number }[];
}

interface OtelLogRecord {
  id: number;
  pipeline_run_id: number | null;
  trace_id: string | null;
  span_id: string | null;
  severity_number: number | null;
  severity_text: string | null;
  body: string | null;
  attributes: string | null;
  resource_attrs: string | null;
  observed_at: string | null;
}

interface OtelMetricSummary {
  distinct_metrics: number;
  total_points: number;
  latest_values: {
    metric_name: string;
    metric_type: string;
    value: number | null;
    recorded_at: string | null;
  }[];
}

interface OtelMetricName {
  metric_name: string;
  metric_type: string;
  point_count: number;
  last_recorded: string | null;
}

interface MetricSeriesPoint {
  bucket: string;
  avg_value: number | null;
  max_value: number | null;
  min_value: number | null;
  point_count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatTs(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function truncate(s: string | null, max: number): string {
  if (!s) return "—";
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function parseJson(s: string | null | undefined): Record<string, unknown> | null {
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

const SEVERITY_CLASSES: Record<string, string> = {
  ERROR: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  WARN: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  WARNING: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  INFO: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  DEBUG: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
};

const SEVERITY_BAR_COLORS: Record<string, string> = {
  ERROR: "bg-red-500",
  WARN: "bg-amber-500",
  WARNING: "bg-amber-500",
  INFO: "bg-blue-500",
  DEBUG: "bg-gray-400",
};

const METRIC_TYPE_CLASSES: Record<string, string> = {
  sum: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  gauge: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  histogram: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
};

// ---------------------------------------------------------------------------
// BarChart (same pattern as Telemetry.tsx)
// ---------------------------------------------------------------------------

function BarChart({
  bars,
  maxValue,
  formatLabel,
  xLabels,
  xLabelInterval = 1,
}: {
  bars: { value: number; color: string; title: string }[];
  maxValue: number;
  formatLabel: (v: number) => string;
  xLabels?: string[];
  xLabelInterval?: number;
}) {
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div>
      <div className="flex">
        <div className="flex flex-col justify-between h-40 pr-2 flex-shrink-0 w-14">
          {[...ticks].reverse().map((t) => (
            <span key={t} className="text-[10px] text-gray-400 dark:text-gray-500 text-right leading-none">
              {formatLabel(maxValue * t)}
            </span>
          ))}
        </div>
        <div className="flex items-end gap-[2px] h-40 flex-1">
          {bars.map((b, i) => (
            <div
              key={i}
              className="flex-1 rounded-t transition-all"
              style={{
                height: maxValue > 0 ? `${(b.value / maxValue) * 100}%` : "0%",
                backgroundColor: b.color,
                minHeight: b.value > 0 ? 2 : 0,
              }}
              title={b.title}
            />
          ))}
        </div>
      </div>
      {xLabels && (
        <div className="flex ml-14">
          {xLabels.map((label, i) => (
            <div key={i} className="flex-1 text-[10px] text-gray-400 dark:text-gray-500 text-center">
              {i % xLabelInterval === 0 ? label : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function OtelExplorer() {
  const [activeTab, setActiveTab] = useState<"logs" | "metrics">("logs");
  const [loading, setLoading] = useState(true);

  // Logs state
  const [logSummary, setLogSummary] = useState<OtelLogSummary | null>(null);
  const [logs, setLogs] = useState<OtelLogRecord[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsPage, setLogsPage] = useState(0);
  const [severityFilter, setSeverityFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [traceFilter, setTraceFilter] = useState("");
  const [selectedLog, setSelectedLog] = useState<OtelLogRecord | null>(null);

  // Metrics state
  const [metricSummary, setMetricSummary] = useState<OtelMetricSummary | null>(null);
  const [metricNames, setMetricNames] = useState<OtelMetricName[]>([]);
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null);
  const [metricSeries, setMetricSeries] = useState<MetricSeriesPoint[]>([]);

  const PAGE_SIZE = 50;

  // -- Fetch logs --
  const fetchLogSummary = useCallback(async () => {
    try {
      const res = await fetch("/api/otel/logs/summary");
      if (res.ok) setLogSummary(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchLogs = useCallback(async () => {
    const params = new URLSearchParams();
    if (severityFilter) params.set("severity", severityFilter);
    if (searchFilter) params.set("search", searchFilter);
    if (traceFilter) params.set("trace_id", traceFilter);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(logsPage * PAGE_SIZE));

    try {
      const res = await fetch(`/api/otel/logs?${params}`);
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs);
        setLogsTotal(data.total);
      }
    } catch { /* ignore */ }
  }, [severityFilter, searchFilter, traceFilter, logsPage]);

  // -- Fetch metrics --
  const fetchMetrics = useCallback(async () => {
    try {
      const [sumRes, namesRes] = await Promise.all([
        fetch("/api/otel/metrics/summary"),
        fetch("/api/otel/metrics/names"),
      ]);
      if (sumRes.ok) setMetricSummary(await sumRes.json());
      if (namesRes.ok) setMetricNames(await namesRes.json());
    } catch { /* ignore */ }
  }, []);

  const fetchMetricSeries = useCallback(async (name: string) => {
    try {
      const res = await fetch(`/api/otel/metrics/series?metric_name=${encodeURIComponent(name)}`);
      if (res.ok) setMetricSeries(await res.json());
    } catch { /* ignore */ }
  }, []);

  // -- Initial load --
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchLogSummary(), fetchLogs(), fetchMetrics()]).finally(() =>
      setLoading(false)
    );
  }, [fetchLogSummary, fetchLogs, fetchMetrics]);

  // -- Refetch logs on filter/page change --
  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  // -- Fetch series when metric selected --
  useEffect(() => {
    if (selectedMetric) void fetchMetricSeries(selectedMetric);
    else setMetricSeries([]);
  }, [selectedMetric, fetchMetricSeries]);

  if (loading) {
    return (
      <div className="text-center py-12 text-gray-500 dark:text-gray-400">
        Loading OTEL data...
      </div>
    );
  }

  const tabBtn = (tab: typeof activeTab, label: string) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
        activeTab === tab
          ? "border-primary-600 text-primary-600 dark:text-primary-400"
          : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700"
      }`}
    >
      {label}
    </button>
  );

  const totalPages = Math.ceil(logsTotal / PAGE_SIZE);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-1">
        OTEL Explorer
      </h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Browse raw OpenTelemetry log records and metric data points from pipeline runs.
      </p>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        {tabBtn("logs", "Logs")}
        {tabBtn("metrics", "Metrics")}
      </div>

      {/* ================================================================ */}
      {/* LOGS TAB                                                         */}
      {/* ================================================================ */}
      {activeTab === "logs" && (
        <div>
          {/* Summary cards */}
          {logSummary && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {formatNumber(logSummary.total_logs)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Total Logs
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {formatNumber(logSummary.distinct_traces)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Distinct Traces
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {formatNumber(logSummary.recent_count)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Last 24h
                </div>
              </div>
              {/* Severity breakdown */}
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2 text-center">
                  By Severity
                </div>
                {logSummary.by_severity.length > 0 ? (
                  <>
                    <div className="flex h-3 rounded-full overflow-hidden mb-2">
                      {logSummary.by_severity.map((s) => (
                        <div
                          key={s.severity_text}
                          className={SEVERITY_BAR_COLORS[s.severity_text ?? ""] ?? "bg-gray-400"}
                          style={{
                            width: `${(s.cnt / logSummary.total_logs) * 100}%`,
                          }}
                          title={`${s.severity_text}: ${s.cnt}`}
                        />
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center">
                      {logSummary.by_severity.map((s) => (
                        <span key={s.severity_text} className="text-[10px] text-gray-500 dark:text-gray-400">
                          {s.severity_text ?? "UNSET"}: {s.cnt}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-gray-400 text-center">No data</div>
                )}
              </div>
            </div>
          )}

          {/* Filter bar */}
          <div className="flex flex-wrap gap-3 mb-4 items-center">
            <input
              type="text"
              placeholder="Search body / attributes…"
              value={searchFilter}
              onChange={(e) => { setSearchFilter(e.target.value); setLogsPage(0); }}
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 w-64"
            />
            <input
              type="text"
              placeholder="Trace ID…"
              value={traceFilter}
              onChange={(e) => { setTraceFilter(e.target.value); setLogsPage(0); }}
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 w-48 font-mono"
            />
            <select
              value={severityFilter}
              onChange={(e) => { setSeverityFilter(e.target.value); setLogsPage(0); }}
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            >
              <option value="">All Severities</option>
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARN">WARN</option>
              <option value="ERROR">ERROR</option>
            </select>
            {(searchFilter || traceFilter || severityFilter) && (
              <button
                onClick={() => { setSearchFilter(""); setTraceFilter(""); setSeverityFilter(""); setLogsPage(0); }}
                className="text-xs text-primary-600 dark:text-primary-400 hover:underline"
              >
                Clear filters
              </button>
            )}
            <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">
              {logsTotal.toLocaleString()} record{logsTotal !== 1 ? "s" : ""}
            </span>
          </div>

          {/* Logs table */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-4">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-44">
                    Timestamp
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-24">
                    Severity
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                    Body
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-40">
                    Trace ID
                  </th>
                  <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-20">
                    Attrs
                  </th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-400 dark:text-gray-500">
                      No log records found
                    </td>
                  </tr>
                ) : (
                  logs.map((lr) => {
                    const attrs = parseJson(lr.attributes);
                    const attrCount = attrs ? Object.keys(attrs).length : 0;
                    return (
                      <tr
                        key={lr.id}
                        onClick={() => setSelectedLog(lr)}
                        className="hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer"
                      >
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                          {formatTs(lr.observed_at)}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800">
                          {lr.severity_text ? (
                            <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${SEVERITY_CLASSES[lr.severity_text] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                              {lr.severity_text}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">
                          {truncate(lr.body, 120)}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 font-mono text-xs">
                          {lr.trace_id ? truncate(lr.trace_id, 16) : "—"}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-right text-gray-500 dark:text-gray-400 text-xs">
                          {attrCount > 0 ? attrCount : "—"}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-between items-center text-sm">
              <button
                onClick={() => setLogsPage((p) => Math.max(0, p - 1))}
                disabled={logsPage === 0}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
              >
                Previous
              </button>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Page {logsPage + 1} of {totalPages}
              </span>
              <button
                onClick={() => setLogsPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={logsPage >= totalPages - 1}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
              >
                Next
              </button>
            </div>
          )}

          {/* Log detail modal */}
          {selectedLog && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setSelectedLog(null)}>
              <div
                className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-3xl max-h-[85vh] overflow-y-auto mx-4"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
                      Log #{selectedLog.id}
                    </span>
                    {selectedLog.severity_text && (
                      <span className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full ${SEVERITY_CLASSES[selectedLog.severity_text] ?? "bg-gray-100 text-gray-700"}`}>
                        {selectedLog.severity_text}
                      </span>
                    )}
                  </div>
                  <button onClick={() => setSelectedLog(null)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <X size={20} />
                  </button>
                </div>

                <div className="px-6 py-4 space-y-5">
                  {/* Timestamp & IDs */}
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Observed At</div>
                      <div className="text-gray-900 dark:text-gray-100">{formatTs(selectedLog.observed_at)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Severity Number</div>
                      <div className="text-gray-900 dark:text-gray-100">{selectedLog.severity_number ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Trace ID</div>
                      <div className="text-gray-900 dark:text-gray-100 font-mono text-xs break-all">{selectedLog.trace_id ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Span ID</div>
                      <div className="text-gray-900 dark:text-gray-100 font-mono text-xs break-all">{selectedLog.span_id ?? "—"}</div>
                    </div>
                  </div>

                  {/* Body */}
                  <div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Body</div>
                    <pre className="bg-gray-50 dark:bg-gray-900 rounded-lg p-3 text-xs text-gray-900 dark:text-gray-100 font-mono whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                      {selectedLog.body ?? "—"}
                    </pre>
                  </div>

                  {/* Attributes */}
                  {(() => {
                    const attrs = parseJson(selectedLog.attributes);
                    if (!attrs || Object.keys(attrs).length === 0) return null;
                    return (
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Attributes</div>
                        <div className="bg-gray-50 dark:bg-gray-900 rounded-lg overflow-hidden">
                          <table className="w-full text-xs">
                            <tbody>
                              {Object.entries(attrs).map(([k, v]) => (
                                <tr key={k} className="border-b border-gray-100 dark:border-gray-800">
                                  <td className="px-3 py-1.5 font-mono text-gray-500 dark:text-gray-400 w-1/3 align-top">{k}</td>
                                  <td className="px-3 py-1.5 font-mono text-gray-900 dark:text-gray-100 break-all">
                                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Resource attributes */}
                  {(() => {
                    const resAttrs = parseJson(selectedLog.resource_attrs);
                    if (!resAttrs || Object.keys(resAttrs).length === 0) return null;
                    return (
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Resource Attributes</div>
                        <div className="bg-gray-50 dark:bg-gray-900 rounded-lg overflow-hidden">
                          <table className="w-full text-xs">
                            <tbody>
                              {Object.entries(resAttrs).map(([k, v]) => (
                                <tr key={k} className="border-b border-gray-100 dark:border-gray-800">
                                  <td className="px-3 py-1.5 font-mono text-gray-500 dark:text-gray-400 w-1/3 align-top">{k}</td>
                                  <td className="px-3 py-1.5 font-mono text-gray-900 dark:text-gray-100 break-all">
                                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ================================================================ */}
      {/* METRICS TAB                                                      */}
      {/* ================================================================ */}
      {activeTab === "metrics" && (
        <div>
          {/* Summary cards */}
          {metricSummary && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {metricSummary.distinct_metrics}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Distinct Metrics
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {formatNumber(metricSummary.total_points)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Data Points
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {metricSummary.latest_values.length}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">
                  Active Metrics
                </div>
              </div>
            </div>
          )}

          {/* Metric names table */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-6">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                    Metric Name
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-24">
                    Type
                  </th>
                  <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-28">
                    Latest Value
                  </th>
                  <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-24">
                    Points
                  </th>
                  <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-44">
                    Last Recorded
                  </th>
                </tr>
              </thead>
              <tbody>
                {metricNames.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-400 dark:text-gray-500">
                      No metrics recorded yet
                    </td>
                  </tr>
                ) : (
                  metricNames.map((m) => {
                    const latest = metricSummary?.latest_values.find(
                      (v) => v.metric_name === m.metric_name
                    );
                    const isSelected = selectedMetric === m.metric_name;
                    return (
                      <tr
                        key={m.metric_name}
                        onClick={() =>
                          setSelectedMetric(isSelected ? null : m.metric_name)
                        }
                        className={`cursor-pointer ${
                          isSelected
                            ? "bg-primary-50 dark:bg-primary-900/20"
                            : "hover:bg-gray-50 dark:hover:bg-gray-700/30"
                        }`}
                      >
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">
                          {m.metric_name}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800">
                          <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${METRIC_TYPE_CLASSES[m.metric_type] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                            {m.metric_type}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-right text-gray-900 dark:text-gray-100 font-mono text-xs">
                          {latest?.value != null ? latest.value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—"}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-right text-gray-500 dark:text-gray-400">
                          {m.point_count.toLocaleString()}
                        </td>
                        <td className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 text-right text-gray-500 dark:text-gray-400 text-xs">
                          {formatTs(m.last_recorded)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Time series chart for selected metric */}
          {selectedMetric && metricSeries.length > 0 && (
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">Time Series</div>
                  <div className="text-sm font-mono font-bold text-gray-900 dark:text-gray-100 mt-0.5">
                    {selectedMetric}
                  </div>
                </div>
                <button
                  onClick={() => setSelectedMetric(null)}
                  className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  Close
                </button>
              </div>
              <BarChart
                bars={metricSeries.map((p) => ({
                  value: p.avg_value ?? 0,
                  color: "#6366f1",
                  title: `${p.bucket}\navg: ${p.avg_value?.toLocaleString()}\nmax: ${p.max_value?.toLocaleString()}\nmin: ${p.min_value?.toLocaleString()}\npoints: ${p.point_count}`,
                }))}
                maxValue={Math.max(...metricSeries.map((p) => p.max_value ?? 0))}
                formatLabel={(v) => {
                  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
                  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
                  return v.toFixed(v < 10 ? 2 : 0);
                }}
                xLabels={metricSeries.map((p) => {
                  const d = p.bucket.split("T");
                  const second = d[1];
                  return second ? second.slice(0, 5) : p.bucket;
                })}
                xLabelInterval={Math.max(1, Math.floor(metricSeries.length / 12))}
              />
            </div>
          )}

          {selectedMetric && metricSeries.length === 0 && (
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 text-center text-sm text-gray-400 dark:text-gray-500">
              No time series data for {selectedMetric}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default OtelExplorer;
