import { Fragment, useEffect, useState, useCallback } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TelemetrySummary {
  total_tokens: number;
  total_cost: number;
  run_count: number;
}

/* MLflow types */

interface MLflowExperiment {
  experiment_id: string;
  name: string;
  lifecycle_stage: string;
}

interface MLflowMetric {
  key: string;
  value: number;
}

interface MLflowParam {
  key: string;
  value: string;
}

interface MLflowRunInfo {
  run_id: string;
  status: string;
  start_time: number;
  end_time: number;
}

interface MLflowRun {
  info: MLflowRunInfo;
  data: {
    metrics: MLflowMetric[];
    params: MLflowParam[];
  };
}

interface TrendPoint {
  date: string;
  total_tokens: number;
  cost_usd: number;
  run_count: number;
}

interface TrendsResponse {
  trends: TrendPoint[];
}

interface CostBreakdownEntry {
  pipeline_slug: string;
  pipeline_name: string;
  model: string;
  skill_name: string;
  total_cost: number;
  total_tokens: number;
}

interface CostResponse {
  breakdown: CostBreakdownEntry[];
}

type DateRange = "7" | "30" | "90" | "all";

const DATE_RANGE_LABELS: Record<DateRange, string> = {
  "7": "Last 7 days",
  "30": "Last 30 days",
  "90": "Last 90 days",
  all: "All",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format a number as a compact token count: 142000 -> "142k". */
function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    const val = n / 1_000_000;
    return val % 1 === 0 ? `${val}M` : `${val.toFixed(1)}M`;
  }
  if (n >= 1_000) {
    const val = n / 1_000;
    return val % 1 === 0 ? `${val}k` : `${val.toFixed(1)}k`;
  }
  return String(n);
}

/** Format a number as USD: 4.2 -> "$4.20", 0.009 -> "$0.01". */
function formatCost(n: number): string {
  if (n >= 1000) {
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `$${n.toFixed(2)}`;
}

/** Format a date string "2026-06-01" -> "Jun 1". */
function shortDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

/** Filter trends by date range. */
function filterByRange(trends: TrendPoint[], range: DateRange): TrendPoint[] {
  if (range === "all") return trends;

  const days = Number(range);
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  return trends.filter((t) => t.date >= cutoffStr);
}

/** Format a unix-ms timestamp to a readable date/time string. */
function formatTimestamp(ms: number): string {
  if (!ms) return "—";
  try {
    const d = new Date(ms);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

/** Format duration in ms to human-readable. */
function formatDuration(startMs: number, endMs: number): string {
  if (!startMs || !endMs || endMs <= startMs) return "—";
  const diffSec = Math.floor((endMs - startMs) / 1000);
  if (diffSec < 60) return `${diffSec}s`;
  const mins = Math.floor(diffSec / 60);
  const secs = diffSec % 60;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hrs}h ${remMins}m`;
}

/** Filter breakdown by date range (uses trends to know which dates are in range). */
function filterBreakdownByRange(
  breakdown: CostBreakdownEntry[],
  _range: DateRange,
): CostBreakdownEntry[] {
  // The backend cost endpoint doesn't include dates per entry,
  // so we return all breakdown entries and let the API handle filtering.
  // If the backend supported a date parameter, we'd filter here.
  return breakdown;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface RunMetrics {
  total_runs: number;
  success_rate: number;
  avg_duration_seconds: number;
  avg_queue_seconds: number;
}

interface RunTrendPoint {
  date: string;
  run_count: number;
  avg_duration: number;
  avg_queue_seconds: number;
  success_rate: number;
}

interface RunBreakdownEntry {
  slug: string;
  pipeline_name: string;
  total_runs: number;
  success_rate: number;
  avg_duration: number;
  max_duration: number;
  avg_queue_seconds: number;
}

function formatDurationShort(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
}

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
        {/* Y-axis */}
        <div className="flex flex-col justify-between h-40 pr-2 flex-shrink-0 w-12">
          {[...ticks].reverse().map((t) => (
            <span key={t} className="text-[10px] text-gray-400 dark:text-gray-500 text-right leading-none">
              {formatLabel(maxValue * t)}
            </span>
          ))}
        </div>
        {/* Bars */}
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
      {/* X-axis */}
      {xLabels && (
        <div className="flex ml-12">
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

function Telemetry() {
  const [summary, setSummary] = useState<TelemetrySummary | null>(null);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [breakdown, setBreakdown] = useState<CostBreakdownEntry[]>([]);

  const [runMetrics, setRunMetrics] = useState<RunMetrics | null>(null);
  const [runTrends, setRunTrends] = useState<RunTrendPoint[]>([]);
  const [runBreakdown, setRunBreakdown] = useState<RunBreakdownEntry[]>([]);

  interface DimensionItem {
    dimension_value: string;
    total: number;
    run_count: number;
  }
  interface DimensionData {
    cost_by_model: DimensionItem[];
    cost_by_source: DimensionItem[];
    tokens_by_model: DimensionItem[];
    tokens_by_type: DimensionItem[];
    tokens_by_source: DimensionItem[];
    loc_by_type: DimensionItem[];
  }
  const [dimensions, setDimensions] = useState<DimensionData | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dateRange, setDateRange] = useState<DateRange>("30");

  /* ---------- MLflow state ---------- */
  const [mlflowExpanded, setMlflowExpanded] = useState(false);
  const [mlflowExperiments, setMlflowExperiments] = useState<MLflowExperiment[]>([]);
  const [mlflowAvailable, setMlflowAvailable] = useState<boolean | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [mlflowRuns, setMlflowRuns] = useState<MLflowRun[]>([]);
  const [mlflowRunsLoading, setMlflowRunsLoading] = useState(false);

  /* ---------- Fetch all telemetry data ---------- */

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [summaryRes, trendsRes, costRes, runMetricsRes, runTrendsRes, runBreakdownRes] = await Promise.all([
        fetch("/api/telemetry/summary"),
        fetch("/api/telemetry/trends"),
        fetch("/api/telemetry/cost"),
        fetch("/api/telemetry/run-metrics"),
        fetch("/api/telemetry/run-trends"),
        fetch("/api/telemetry/run-breakdown"),
      ]);

      if (!summaryRes.ok || !trendsRes.ok || !costRes.ok) {
        const failedStatus = !summaryRes.ok
          ? summaryRes.status
          : !trendsRes.ok
            ? trendsRes.status
            : costRes.status;
        throw new Error(`API returned ${failedStatus}`);
      }

      const summaryData: TelemetrySummary = await summaryRes.json();
      const trendsData: TrendsResponse = await trendsRes.json();
      const costData: CostResponse = await costRes.json();

      setSummary(summaryData);
      setTrends(trendsData.trends ?? []);
      setBreakdown(costData.breakdown ?? []);

      if (runMetricsRes.ok) setRunMetrics(await runMetricsRes.json());
      if (runTrendsRes.ok) setRunTrends(await runTrendsRes.json());
      if (runBreakdownRes.ok) setRunBreakdown(await runBreakdownRes.json());

      try {
        const dimRes = await fetch("/api/telemetry/dimensions");
        if (dimRes.ok) setDimensions(await dimRes.json());
      } catch { /* non-critical */ }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch telemetry data",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  /* ---------- Fetch MLflow experiments ---------- */

  const fetchMLflowExperiments = useCallback(async () => {
    try {
      const res = await fetch("/mlflow/api/2.0/mlflow/experiments/search");
      if (!res.ok) {
        setMlflowAvailable(false);
        return;
      }
      const data = await res.json();
      const experiments: MLflowExperiment[] = data.experiments ?? [];
      setMlflowExperiments(experiments);
      setMlflowAvailable(true);
      // Auto-select first experiment if none selected
      const first = experiments[0];
      if (first && !selectedExperimentId) {
        setSelectedExperimentId(first.experiment_id);
      }
    } catch {
      setMlflowAvailable(false);
    }
  }, [selectedExperimentId]);

  // Fetch experiments when the section is expanded
  useEffect(() => {
    if (mlflowExpanded && mlflowAvailable === null) {
      void fetchMLflowExperiments();
    }
  }, [mlflowExpanded, mlflowAvailable, fetchMLflowExperiments]);

  /* ---------- Fetch MLflow runs for selected experiment ---------- */

  const fetchMLflowRuns = useCallback(async (experimentId: string) => {
    setMlflowRunsLoading(true);
    try {
      const res = await fetch("/mlflow/api/2.0/mlflow/runs/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ experiment_ids: [experimentId] }),
      });
      if (!res.ok) {
        setMlflowRuns([]);
        return;
      }
      const data = await res.json();
      setMlflowRuns(data.runs ?? []);
    } catch {
      setMlflowRuns([]);
    } finally {
      setMlflowRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedExperimentId && mlflowExpanded) {
      void fetchMLflowRuns(selectedExperimentId);
    }
  }, [selectedExperimentId, mlflowExpanded, fetchMLflowRuns]);

  /* ---------- Derived data ---------- */

  const filteredTrends = filterByRange(trends, dateRange);
  const filteredBreakdown = filterBreakdownByRange(breakdown, dateRange);

  // Sort breakdown by cost descending
  const sortedBreakdown = [...filteredBreakdown].sort(
    (a, b) => b.total_cost - a.total_cost,
  );

  // Group breakdown by pipeline for subtotals
  const pipelineGroups: {
    pipeline_slug: string;
    pipeline_name: string;
    entries: CostBreakdownEntry[];
    subtotal_cost: number;
    subtotal_tokens: number;
  }[] = [];

  const pipelineMap = new Map<string, typeof pipelineGroups[number]>();
  for (const entry of sortedBreakdown) {
    let group = pipelineMap.get(entry.pipeline_slug);
    if (!group) {
      group = {
        pipeline_slug: entry.pipeline_slug,
        pipeline_name: entry.pipeline_name,
        entries: [],
        subtotal_cost: 0,
        subtotal_tokens: 0,
      };
      pipelineMap.set(entry.pipeline_slug, group);
      pipelineGroups.push(group);
    }
    group.entries.push(entry);
    group.subtotal_cost += entry.total_cost;
    group.subtotal_tokens += entry.total_tokens;
  }

  // Sort groups by subtotal cost descending
  pipelineGroups.sort((a, b) => b.subtotal_cost - a.subtotal_cost);

  // Chart maximums
  const maxCost = filteredTrends.length > 0
    ? Math.max(...filteredTrends.map((t) => t.cost_usd))
    : 0;
  const maxTokens = filteredTrends.length > 0
    ? Math.max(...filteredTrends.map((t) => t.total_tokens))
    : 0;

  // Decide how many x-axis labels to show (every Nth label)
  const xLabelInterval = filteredTrends.length > 15
    ? Math.ceil(filteredTrends.length / 10)
    : 1;

  const hasData =
    (summary && (summary.total_cost > 0 || summary.total_tokens > 0 || summary.run_count > 0)) ||
    trends.length > 0 ||
    breakdown.length > 0 ||
    (runMetrics && runMetrics.total_runs > 0);

  /* ---------- Render ---------- */

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Telemetry Dashboard</h1>
        <div className="flex gap-1 flex-wrap">
          {(Object.keys(DATE_RANGE_LABELS) as DateRange[]).map((key) => (
            <button
              key={key}
              className={
                dateRange === key
                  ? "text-sm font-medium px-3 py-1.5 rounded-lg border border-primary-600 bg-primary-600 text-white cursor-pointer transition-all"
                  : "text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all"
              }
              onClick={() => setDateRange(key)}
            >
              {DATE_RANGE_LABELS[key]}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Aggregated cost, token usage, and duration trends across all pipelines.
      </p>

      {/* Loading state */}
      {loading && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading telemetry data...</div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load telemetry data</p>
          <p className="text-sm">{error}</p>
          <button
            className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer"
            onClick={() => void fetchData()}
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && !hasData && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="font-semibold mb-1">No telemetry data yet</p>
          <p className="text-sm">
            Telemetry metrics will appear here once pipelines start reporting
            token usage and cost data.
          </p>
        </div>
      )}

      {/* Main content */}
      {!loading && !error && hasData && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
            {summary && summary.total_cost > 0 && (
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Total Cost</div>
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{formatCost(summary.total_cost)}</div>
              </div>
            )}
            {summary && summary.total_tokens > 0 && (
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Total Tokens</div>
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{formatTokens(summary.total_tokens)}</div>
              </div>
            )}
            {runMetrics && (
              <>
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Total Runs</div>
                  <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{runMetrics.total_runs.toLocaleString()}</div>
                </div>
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Success Rate</div>
                  <div className={`text-2xl font-bold ${runMetrics.success_rate >= 80 ? "text-emerald-600" : runMetrics.success_rate >= 50 ? "text-amber-600" : "text-red-600"}`}>{runMetrics.success_rate}%</div>
                </div>
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Avg Duration</div>
                  <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{formatDurationShort(runMetrics.avg_duration_seconds)}</div>
                </div>
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Avg Queue</div>
                  <div className={`text-2xl font-bold ${runMetrics.avg_queue_seconds > 300 ? "text-amber-600" : "text-gray-900 dark:text-gray-100"}`}>{formatDurationShort(runMetrics.avg_queue_seconds)}</div>
                </div>
              </>
            )}
          </div>

          {/* Model & dimension breakdown */}
          {dimensions && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
              {/* Cost by source */}
              {dimensions.cost_by_source.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Cost by Source</div>
                  {(() => {
                    const total = dimensions.cost_by_source.reduce((s, d) => s + d.total, 0);
                    const colors: Record<string, string> = { main: "bg-primary-500", subagent: "bg-violet-500", auxiliary: "bg-amber-500" };
                    return (
                      <>
                        <div className="flex h-3 rounded-full overflow-hidden mb-3">
                          {dimensions.cost_by_source.map((d) => (
                            <div
                              key={d.dimension_value}
                              className={`${colors[d.dimension_value] ?? "bg-gray-400"}`}
                              style={{ width: `${(d.total / total) * 100}%` }}
                              title={`${d.dimension_value}: ${formatCost(d.total)}`}
                            />
                          ))}
                        </div>
                        <div className="space-y-1">
                          {dimensions.cost_by_source.map((d) => (
                            <div key={d.dimension_value} className="flex justify-between text-xs">
                              <span className="text-gray-600 dark:text-gray-400 capitalize">{d.dimension_value}</span>
                              <span className="text-gray-900 dark:text-gray-100 font-medium">{formatCost(d.total)}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    );
                  })()}
                </div>
              )}

              {/* Tokens by type */}
              {dimensions.tokens_by_type.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Tokens by Type</div>
                  {(() => {
                    const total = dimensions.tokens_by_type.reduce((s, d) => s + d.total, 0);
                    const colors: Record<string, string> = { input: "bg-blue-500", output: "bg-emerald-500", cacheRead: "bg-gray-300 dark:bg-gray-600", cacheCreation: "bg-amber-400" };
                    return (
                      <>
                        <div className="flex h-3 rounded-full overflow-hidden mb-3">
                          {dimensions.tokens_by_type.map((d) => (
                            <div
                              key={d.dimension_value}
                              className={`${colors[d.dimension_value] ?? "bg-gray-400"}`}
                              style={{ width: `${(d.total / total) * 100}%` }}
                              title={`${d.dimension_value}: ${formatTokens(d.total)}`}
                            />
                          ))}
                        </div>
                        <div className="space-y-1">
                          {dimensions.tokens_by_type.map((d) => (
                            <div key={d.dimension_value} className="flex justify-between text-xs">
                              <span className="text-gray-600 dark:text-gray-400">{d.dimension_value}</span>
                              <span className="text-gray-900 dark:text-gray-100 font-medium">{formatTokens(d.total)}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    );
                  })()}
                </div>
              )}

              {/* Tokens by source */}
              {dimensions.tokens_by_source.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Tokens by Source</div>
                  {(() => {
                    const total = dimensions.tokens_by_source.reduce((s, d) => s + d.total, 0);
                    const colors: Record<string, string> = { main: "bg-primary-500", subagent: "bg-violet-500", auxiliary: "bg-amber-500" };
                    return (
                      <>
                        <div className="flex h-3 rounded-full overflow-hidden mb-3">
                          {dimensions.tokens_by_source.map((d) => (
                            <div
                              key={d.dimension_value}
                              className={`${colors[d.dimension_value] ?? "bg-gray-400"}`}
                              style={{ width: `${(d.total / total) * 100}%` }}
                              title={`${d.dimension_value}: ${formatTokens(d.total)}`}
                            />
                          ))}
                        </div>
                        <div className="space-y-1">
                          {dimensions.tokens_by_source.map((d) => (
                            <div key={d.dimension_value} className="flex justify-between text-xs">
                              <span className="text-gray-600 dark:text-gray-400 capitalize">{d.dimension_value}</span>
                              <span className="text-gray-900 dark:text-gray-100 font-medium">{formatTokens(d.total)}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    );
                  })()}
                </div>
              )}

              {/* Lines of code */}
              {dimensions.loc_by_type.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                  <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Code Churn</div>
                  <div className="space-y-2">
                    {dimensions.loc_by_type.map((d) => (
                      <div key={d.dimension_value}>
                        <div className="flex justify-between text-xs mb-0.5">
                          <span className={d.dimension_value === "added" ? "text-emerald-600" : "text-red-600"}>
                            {d.dimension_value === "added" ? "+" : "-"}{d.total.toLocaleString()} lines
                          </span>
                          <span className="text-gray-400">{d.run_count} runs</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Model */}
                  {dimensions.cost_by_model.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-700">
                      <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">Model</div>
                      {dimensions.cost_by_model.map((d) => (
                        <div key={d.dimension_value} className="text-sm font-medium text-gray-900 dark:text-gray-100">
                          {d.dimension_value}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Cost + Token trend charts side by side */}
          {filteredTrends.length > 0 && (maxCost > 0 || maxTokens > 0) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
              {maxCost > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Daily Cost</h3>
                  <BarChart
                    bars={filteredTrends.map((t) => ({ value: t.cost_usd, color: "#1a56db", title: `${shortDate(t.date)}: ${formatCost(t.cost_usd)}` }))}
                    maxValue={maxCost}
                    formatLabel={formatCost}
                    xLabels={filteredTrends.map((t) => shortDate(t.date))}
                    xLabelInterval={xLabelInterval}
                  />
                </div>
              )}
              {maxTokens > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Daily Token Usage</h3>
                  <BarChart
                    bars={filteredTrends.map((t) => ({ value: t.total_tokens, color: "#7c3aed", title: `${shortDate(t.date)}: ${formatTokens(t.total_tokens)}` }))}
                    maxValue={maxTokens}
                    formatLabel={formatTokens}
                    xLabels={filteredTrends.map((t) => shortDate(t.date))}
                    xLabelInterval={xLabelInterval}
                  />
                </div>
              )}
            </div>
          )}

          {/* Cost breakdown table */}
          {sortedBreakdown.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Cost Breakdown</h2>
              <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                <thead>
                  <tr>
                    <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Pipeline</th>
                    <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Model</th>
                    <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Skill</th>
                    <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 text-right">Cost</th>
                    <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 text-right">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {pipelineGroups.map((group) => (
                    <Fragment key={group.pipeline_slug}>
                      {/* Pipeline group header (only show if multiple groups) */}
                      {pipelineGroups.length > 1 && (
                        <tr className="bg-gray-50 dark:bg-gray-700/50 font-semibold">
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100" colSpan={3}>{group.pipeline_name}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">
                            {formatCost(group.subtotal_cost)}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">
                            {formatTokens(group.subtotal_tokens)}
                          </td>
                        </tr>
                      )}
                      {group.entries.map((entry, i) => (
                        <tr key={`${group.pipeline_slug}-${i}`}>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            {pipelineGroups.length > 1
                              ? ""
                              : entry.pipeline_name}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{entry.model || "—"}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{entry.skill_name || "—"}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">
                            {formatCost(entry.total_cost)}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">
                            {formatTokens(entry.total_tokens)}
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Run trends charts */}
      {runTrends.length > 0 && (() => {
        const maxDur = Math.max(...runTrends.map((t) => t.avg_duration));
        const maxQueue = Math.max(...runTrends.map((t) => t.avg_queue_seconds), 1);
        const maxRuns = Math.max(...runTrends.map((t) => t.run_count));
        const labelInterval = runTrends.length > 15 ? Math.ceil(runTrends.length / 10) : 1;

        return (
          <>
            {/* Duration + Queue side by side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Avg Duration by Day</h3>
                <BarChart
                  bars={runTrends.map((t) => ({ value: t.avg_duration, color: "#818cf8", title: `${shortDate(t.date)}: ${formatDurationShort(t.avg_duration)}` }))}
                  maxValue={maxDur}
                  formatLabel={formatDurationShort}
                  xLabels={runTrends.map((t) => shortDate(t.date))}
                  xLabelInterval={labelInterval}
                />
              </div>

              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Avg Queue Time by Day</h3>
                <BarChart
                  bars={runTrends.map((t) => ({
                    value: t.avg_queue_seconds,
                    color: t.avg_queue_seconds > 300 ? "rgba(245, 158, 11, 0.6)" : "rgba(16, 185, 129, 0.6)",
                    title: `${shortDate(t.date)}: ${formatDurationShort(t.avg_queue_seconds)} queue`,
                  }))}
                  maxValue={maxQueue}
                  formatLabel={formatDurationShort}
                  xLabels={runTrends.map((t) => shortDate(t.date))}
                  xLabelInterval={labelInterval}
                />
              </div>
            </div>

            {/* Runs per day + Success rate side by side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Runs per Day</h3>
                <BarChart
                  bars={runTrends.map((t) => ({ value: t.run_count, color: "#60a5fa", title: `${shortDate(t.date)}: ${t.run_count} runs` }))}
                  maxValue={maxRuns}
                  formatLabel={(v) => String(Math.round(v))}
                  xLabels={runTrends.map((t) => shortDate(t.date))}
                  xLabelInterval={labelInterval}
                />
              </div>

              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Success Rate by Day</h3>
                <BarChart
                  bars={runTrends.map((t) => ({
                    value: t.success_rate,
                    color: t.success_rate >= 80 ? "rgba(16, 185, 129, 0.6)" : t.success_rate >= 50 ? "rgba(245, 158, 11, 0.6)" : "rgba(239, 68, 68, 0.6)",
                    title: `${shortDate(t.date)}: ${t.success_rate}% success`,
                  }))}
                  maxValue={100}
                  formatLabel={(v) => `${Math.round(v)}%`}
                  xLabels={runTrends.map((t) => shortDate(t.date))}
                  xLabelInterval={labelInterval}
                />
              </div>
            </div>
          </>
        );
      })()}

      {/* Pipeline breakdown table */}
      {runBreakdown.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Pipeline Breakdown</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Pipeline</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Runs</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Success</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Avg Duration</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Max Duration</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Avg Queue</th>
              </tr>
            </thead>
            <tbody>
              {runBreakdown.map((r) => (
                <tr key={r.slug} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-medium">{r.pipeline_name}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">{r.total_runs}</td>
                  <td className={`px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-right font-medium ${r.success_rate >= 80 ? "text-emerald-600" : r.success_rate >= 50 ? "text-amber-600" : "text-red-600"}`}>{r.success_rate}%</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">{formatDurationShort(r.avg_duration)}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-right">{formatDurationShort(r.max_duration)}</td>
                  <td className={`px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-right ${r.avg_queue_seconds > 300 ? "text-amber-600 font-medium" : "text-gray-900 dark:text-gray-100"}`}>{formatDurationShort(r.avg_queue_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* MLflow Experiments section (collapsible, always rendered) */}
      <div className="mt-8">
        <button
          className="flex items-center gap-2 bg-transparent border-none text-left cursor-pointer p-0"
          onClick={() => setMlflowExpanded((prev) => !prev)}
          aria-expanded={mlflowExpanded}
        >
          <span className="text-gray-400 dark:text-gray-500">
            {mlflowExpanded ? "▼" : "▶"}
          </span>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">MLflow Experiments</h2>
        </button>

        {mlflowExpanded && (
          <div className="mt-4">
            {/* Unavailable state */}
            {mlflowAvailable === false && (
              <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                MLflow data not available
              </div>
            )}

            {/* Loading state (initial fetch) */}
            {mlflowAvailable === null && (
              <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                Loading MLflow data...
              </div>
            )}

            {/* Available: show experiment selector + runs */}
            {mlflowAvailable === true && (
              <>
                {mlflowExperiments.length === 0 ? (
                  <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                    No experiments found
                  </div>
                ) : (
                  <>
                    {/* Experiment selector */}
                    <div className="flex items-center gap-3 mb-4">
                      <label
                        htmlFor="mlflow-experiment-select"
                        className="text-sm font-medium text-gray-700 dark:text-gray-300"
                      >
                        Experiment:
                      </label>
                      <select
                        id="mlflow-experiment-select"
                        className="text-sm px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
                        value={selectedExperimentId ?? ""}
                        onChange={(e) => setSelectedExperimentId(e.target.value)}
                      >
                        {mlflowExperiments.map((exp) => (
                          <option key={exp.experiment_id} value={exp.experiment_id}>
                            {exp.name} ({exp.lifecycle_stage})
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Runs table */}
                    {mlflowRunsLoading && (
                      <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                        Loading runs...
                      </div>
                    )}

                    {!mlflowRunsLoading && mlflowRuns.length === 0 && (
                      <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                        No runs found for this experiment
                      </div>
                    )}

                    {!mlflowRunsLoading && mlflowRuns.length > 0 && (
                      <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                        <thead>
                          <tr>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Run ID</th>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Status</th>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Start Time</th>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">End Time</th>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Duration</th>
                            <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Key Metrics</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlflowRuns.map((run) => {
                            const metricsStr = (run.data?.metrics ?? [])
                              .map((m) => `${m.key}: ${formatTokens(m.value)}`)
                              .join(", ");
                            const paramsStr = (run.data?.params ?? [])
                              .map((p) => `${p.key}=${p.value}`)
                              .join(", ");
                            const combined = [metricsStr, paramsStr]
                              .filter(Boolean)
                              .join(" | ");

                            return (
                              <tr key={run.info.run_id}>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs" title={run.info.run_id}>
                                  {run.info.run_id.slice(0, 8)}
                                </td>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                                  <span
                                    className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                                      run.info.status === "FINISHED"
                                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                                        : run.info.status === "FAILED"
                                          ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
                                          : run.info.status === "RUNNING"
                                            ? "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300"
                                            : ""
                                    }`}
                                  >
                                    {run.info.status}
                                  </span>
                                </td>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{formatTimestamp(run.info.start_time)}</td>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{formatTimestamp(run.info.end_time)}</td>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{formatDuration(run.info.start_time, run.info.end_time)}</td>
                                <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-xs text-gray-500 dark:text-gray-400 max-w-[300px] truncate">{combined || "—"}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default Telemetry;
