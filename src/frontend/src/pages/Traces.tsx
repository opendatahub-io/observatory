import { useEffect, useState, useCallback } from "react";

interface TraceSummary {
  total_events: number;
  runs_with_traces: number;
  total_packages: number;
  events_by_type: { event_type: string; cnt: number }[];
  events_by_source: { source: string; cnt: number }[];
}

interface ToolUsage {
  tool_name: string;
  call_count: number;
  run_count: number;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function Traces() {
  const [summary, setSummary] = useState<TraceSummary | null>(null);
  const [tools, setTools] = useState<ToolUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"overview" | "tools">("overview");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, toolRes] = await Promise.all([
        fetch("/api/traces/summary"),
        fetch("/api/traces/tools"),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (toolRes.ok) setTools(await toolRes.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  if (loading) {
    return <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading trace data...</div>;
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

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-1">Traces</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Agent execution traces — tool calls, reasoning, subagents, and runtime packages.
      </p>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{formatNumber(summary.total_events)}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Events</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.runs_with_traces}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Runs Traced</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{formatNumber(summary.total_packages)}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Packages</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.events_by_type.length}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Event Types</div>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        {tabBtn("overview", "Event Types")}
        {tabBtn("tools", "Tool Usage")}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && summary && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Event type breakdown */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Events by Type</span>
            </div>
            {summary.events_by_type.map((t) => {
              const maxCount = summary.events_by_type[0]?.cnt ?? 1;
              return (
                <div key={t.event_type} className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-sm text-gray-900 dark:text-gray-100 font-mono">{t.event_type}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">{t.cnt.toLocaleString()}</span>
                  </div>
                  <div className="h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-400 dark:bg-primary-500 rounded-full"
                      style={{ width: `${(t.cnt / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Source breakdown */}
          <div>
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 mb-4">
              <div className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">Events by Source</div>
              {(() => {
                const total = summary.events_by_source.reduce((s, e) => s + e.cnt, 0);
                const colors: Record<string, string> = { otel: "bg-violet-500", job_trace: "bg-emerald-500" };
                return (
                  <>
                    <div className="flex h-4 rounded-full overflow-hidden mb-3">
                      {summary.events_by_source.map((s) => (
                        <div
                          key={s.source}
                          className={colors[s.source] ?? "bg-gray-400"}
                          style={{ width: `${(s.cnt / total) * 100}%` }}
                          title={`${s.source}: ${s.cnt.toLocaleString()}`}
                        />
                      ))}
                    </div>
                    <div className="space-y-1">
                      {summary.events_by_source.map((s) => (
                        <div key={s.source} className="flex justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <span className={`w-3 h-3 rounded-full ${colors[s.source] ?? "bg-gray-400"}`} />
                            <span className="text-gray-700 dark:text-gray-300">{s.source === "otel" ? "OTEL Events" : "Job Trace"}</span>
                          </div>
                          <span className="text-gray-900 dark:text-gray-100 font-medium">{s.cnt.toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  </>
                );
              })()}
            </div>

            {/* What each source provides */}
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">Data Sources</div>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-3 h-3 rounded-full bg-violet-500" />
                    <span className="font-medium text-gray-900 dark:text-gray-100">OTEL Events</span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 ml-5">Structured telemetry — token counts, costs, durations per API call and tool use</p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-3 h-3 rounded-full bg-emerald-500" />
                    <span className="font-medium text-gray-900 dark:text-gray-100">Job Trace</span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 ml-5">Agent reasoning — thinking blocks, tool commands, responses, subagent spawns</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tools tab */}
      {activeTab === "tools" && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Tool</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Calls</th>
                <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Runs</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.tool_name} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono">{t.tool_name}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">{t.call_count.toLocaleString()}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-right">{t.run_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </div>
  );
}

export default Traces;
