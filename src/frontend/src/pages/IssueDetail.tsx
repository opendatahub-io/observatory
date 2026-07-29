import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types (mirror crud.traces.search_trace_content)                    */
/* ------------------------------------------------------------------ */

interface RunRow {
  run_id: number;
  pipeline_slug: string;
  external_id: string | null;
  job: string | null;
  status: string | null;
  started_at: string | null;
  web_url: string | null;
  trace_event_matches: number;
  artifact_matches: number;
}

interface TraceMatch {
  kind: string;
  run_id: number;
  pipeline_slug: string;
  event_type: string;
  line_number: number | null;
  snippet: string;
}

interface ArtifactMatch {
  kind: string;
  artifact_id: number;
  run_id: number;
  pipeline_slug: string;
  file_path: string;
  snippet: string;
}

interface IssueDetailData {
  query: string;
  runs: RunRow[];
  trace_matches: TraceMatch[];
  artifact_matches: ArtifactMatch[];
  run_count: number;
  total_run_count: number;
  match_count: number;
  truncated: boolean;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmtDateTime(s: string | null): string {
  if (!s) return "—";
  const t = new Date(s).getTime();
  if (isNaN(t)) return s;
  return new Date(t).toLocaleString();
}

const STATUS_COLORS: Record<string, string> = {
  success: "text-green-700 dark:text-green-400",
  failed: "text-red-700 dark:text-red-400",
  running: "text-blue-700 dark:text-blue-400",
};

const TH =
  "text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700";
const TD =
  "px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100";

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function IssueDetail() {
  const { key = "" } = useParams();
  const jiraKey = decodeURIComponent(key);
  const [data, setData] = useState<IssueDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/issues/${encodeURIComponent(jiraKey)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load issue");
    } finally {
      setLoading(false);
    }
  }, [jiraKey]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const runs = data?.runs ?? [];
  const traceMatches = data?.trace_matches ?? [];
  const artifactMatches = data?.artifact_matches ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Link
        to="/issues"
        className="text-sm text-primary-600 dark:text-primary-400 hover:underline"
      >
        ← All issues
      </Link>

      <div className="flex items-baseline gap-3 mt-2 mb-1">
        <h2 className="text-xl font-mono font-semibold text-gray-900 dark:text-gray-100">
          {jiraKey}
        </h2>
      </div>

      {data && (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Referenced in <b>{data.total_run_count}</b> run
          {data.total_run_count === 1 ? "" : "s"} · <b>{data.match_count}</b> total
          match{data.match_count === 1 ? "" : "es"}
          {data.truncated && " (showing most recent)"}
        </p>
      )}

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No runs reference {jiraKey}.
        </p>
      ) : (
        <>
          {/* Run history */}
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
            Run history
          </h3>
          <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden bg-white dark:bg-gray-900 mb-8">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr>
                  <th className={TH}>Pipeline</th>
                  <th className={TH}>Run</th>
                  <th className={TH}>Job</th>
                  <th className={TH}>Status</th>
                  <th className={TH}>Started</th>
                  <th className={TH}>Matches</th>
                  <th className={TH}></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.run_id}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
                  >
                    <td className={TD}>
                      <Link
                        to={`/pipelines/${r.pipeline_slug}`}
                        className="text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        {r.pipeline_slug}
                      </Link>
                    </td>
                    <td className={`${TD} font-mono text-xs`}>
                      {r.external_id ?? r.run_id}
                    </td>
                    <td className={TD}>{r.job ?? "—"}</td>
                    <td className={TD}>
                      <span className={STATUS_COLORS[r.status ?? ""] ?? ""}>
                        {r.status ?? "—"}
                      </span>
                    </td>
                    <td className={TD}>{fmtDateTime(r.started_at)}</td>
                    <td className={TD}>
                      <span className="text-gray-600 dark:text-gray-300">
                        {r.trace_event_matches} trace
                        {r.artifact_matches > 0 && `, ${r.artifact_matches} artifact`}
                      </span>
                    </td>
                    <td className={TD}>
                      <Link
                        to={`/traces/${r.run_id}`}
                        className="text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        View trace →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Trace evidence */}
          {(traceMatches.length > 0 || artifactMatches.length > 0) && (
            <>
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                Trace evidence
              </h3>
              <div className="space-y-2">
                {traceMatches.map((m, i) => (
                  <div
                    key={`t-${i}`}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 bg-white dark:bg-gray-900"
                  >
                    <div className="flex items-center gap-2 mb-1 text-xs text-gray-500 dark:text-gray-400">
                      <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono">
                        {m.event_type}
                      </span>
                      <Link
                        to={`/traces/${m.run_id}`}
                        className="text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        {m.pipeline_slug} · run {m.run_id}
                      </Link>
                      {m.line_number != null && <span>line {m.line_number}</span>}
                    </div>
                    <pre className="text-xs font-mono whitespace-pre-wrap break-all text-gray-800 dark:text-gray-200">
                      {m.snippet}
                    </pre>
                  </div>
                ))}
                {artifactMatches.map((m, i) => (
                  <div
                    key={`a-${i}`}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 bg-white dark:bg-gray-900"
                  >
                    <div className="flex items-center gap-2 mb-1 text-xs text-gray-500 dark:text-gray-400">
                      <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono">
                        artifact
                      </span>
                      <Link
                        to={`/traces/${m.run_id}`}
                        className="text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        {m.pipeline_slug} · run {m.run_id}
                      </Link>
                      <span className="truncate">{m.file_path}</span>
                    </div>
                    <pre className="text-xs font-mono whitespace-pre-wrap break-all text-gray-800 dark:text-gray-200">
                      {m.snippet}
                    </pre>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default IssueDetail;
