import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Issue {
  jira_key: string;
  run_count: number;
  pipeline_count: number;
  match_count: number;
  first_seen: string | null;
  last_seen: string | null;
  pipelines: string[];
}

interface IssueList {
  issues: Issue[];
  total: number;
  limit: number;
  offset: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmtDate(s: string | null): string {
  if (!s) return "—";
  const t = new Date(s).getTime();
  if (isNaN(t)) return s;
  return new Date(t).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const BTN =
  "text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer";
const BTN_PRIMARY = `${BTN} bg-primary-600 text-white border-primary-600 hover:bg-primary-700`;
const TH =
  "text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700";
const TD =
  "px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100";
const INP =
  "w-full text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400";

const PAGE_SIZE = 100;

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function Issues() {
  const [data, setData] = useState<IssueList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState(""); // debounced value actually sent
  const [offset, setOffset] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  // Debounce the search box.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(search.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchIssues = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (query) params.set("search", query);
      const res = await fetch(`/api/issues?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load issues");
    } finally {
      setLoading(false);
    }
  }, [query, offset]);

  useEffect(() => {
    fetchIssues();
  }, [fetchIssues]);

  const refreshIndex = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const res = await fetch("/api/issues/refresh", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchIssues();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to rebuild index");
    } finally {
      setRefreshing(false);
    }
  };

  const issues = data?.issues ?? [];
  const total = data?.total ?? 0;
  const pageEnd = offset + issues.length;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Issues
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Jira keys referenced in job traces and artifacts. Click a key for its
            run history and trace evidence.
          </p>
        </div>
        <button className={BTN} onClick={refreshIndex} disabled={refreshing}>
          {refreshing ? "Rebuilding…" : "Rebuild index"}
        </button>
      </div>

      <div className="mb-4 max-w-md">
        <input
          className={INP}
          placeholder="Search issue keys (e.g. RHAISTRAT-2364)…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden bg-white dark:bg-gray-900">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              <th className={TH}>Issue Key</th>
              <th className={TH}>Runs</th>
              <th className={TH}>Pipelines</th>
              <th className={TH}>Matches</th>
              <th className={TH}>Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {loading && issues.length === 0 ? (
              <tr>
                <td className={TD} colSpan={5}>
                  Loading…
                </td>
              </tr>
            ) : issues.length === 0 ? (
              <tr>
                <td className={`${TD} text-gray-500 dark:text-gray-400`} colSpan={5}>
                  {query
                    ? `No issues match “${query}”.`
                    : "No issues indexed yet. Click “Rebuild index” to scan trace data."}
                </td>
              </tr>
            ) : (
              issues.map((it) => (
                <tr
                  key={it.jira_key}
                  className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
                >
                  <td className={TD}>
                    <Link
                      to={`/issues/${encodeURIComponent(it.jira_key)}`}
                      className="font-mono font-medium text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      {it.jira_key}
                    </Link>
                  </td>
                  <td className={TD}>{it.run_count}</td>
                  <td className={TD}>
                    <span className="text-gray-600 dark:text-gray-300">
                      {it.pipelines.join(", ") || it.pipeline_count}
                    </span>
                  </td>
                  <td className={TD}>{it.match_count}</td>
                  <td className={TD}>{fmtDate(it.last_seen)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-3 text-sm text-gray-500 dark:text-gray-400">
        <span>
          {total > 0
            ? `Showing ${offset + 1}–${pageEnd} of ${total} issue${total === 1 ? "" : "s"}`
            : ""}
        </span>
        <div className="flex gap-2">
          <button
            className={BTN}
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            className={BTN_PRIMARY}
            disabled={pageEnd >= total || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export default Issues;
