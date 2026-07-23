import { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronRight, ChevronDown } from "lucide-react";
import HealthDot from "../components/HealthDot";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Skill {
  repo_url: string;
  branch?: string;
  purpose?: string;
}

interface SharedLib {
  repo_url: string;
  purpose?: string;
}

interface JiraContract {
  project: string;
  labels?: string[];
}

interface PipelineImage {
  name: string;
  ref?: string;
}

interface TelemetryConfig {
  collector_type: string;
  endpoint?: string;
  status?: string;
}

interface ArtifactConfig {
  results_repo: string;
  status?: string;
}

interface Pipeline {
  id: number;
  slug: string;
  name: string;
  description?: string;
  owner?: string;
  repo_url?: string;
  platform?: string;
  cron?: string;
  expected_interval_minutes?: number;
  timeout_minutes?: number;
  status?: string;
  health?: string;
  created_at?: string;
  updated_at?: string;
  /* Optional metadata sub-resources */
  skills?: Skill[];
  shared_libs?: SharedLib[];
  jira_contracts?: JiraContract[];
  images?: PipelineImage[];
  telemetry_config?: TelemetryConfig[];
  artifact_config?: ArtifactConfig[];
}

interface Run {
  id: number;
  pipeline_id: number;
  external_id: string;
  job: string;
  queued_at: string | null;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  status: string;
  ref: string;
  web_url: string;
  artifacts_scraped: boolean;
  created_at: string;
}

interface RunsResponse {
  runs: Run[];
  total: number;
  page: number;
  per_page: number;
}

interface ArtifactFile {
  id: number;
  source: string;
  source_ref: string | null;
  file_path: string;
  file_size: number | null;
  mime_type: string | null;
}

interface ArtifactListResponse {
  artifacts: ArtifactFile[];
  total: number;
}

interface CIJobScript {
  phase: string;
  step_order: number;
  command: string;
}

interface CIJobVariable {
  key: string;
  value: string | null;
  masked: boolean;
}

interface CIJob {
  id: number;
  name: string;
  stage: string | null;
  image: string | null;
  timeout: string | null;
  extends: string | null;
  resource_group: string | null;
  allow_failure: boolean;
  tags: string[];
  variables: CIJobVariable[];
  scripts: CIJobScript[];
}

interface CIInclude {
  id: number;
  include_type: string;
  project: string | null;
  file: string | null;
  ref: string | null;
}

interface CIDefinitionResponse {
  jobs: CIJob[];
  includes: CIInclude[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Turn a cron expression into a rough human-readable string. */
function humanCron(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length < 5) return cron;

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  // Every N hours: "0 */N * * *"
  if (
    minute === "0" &&
    hour !== undefined && hour.startsWith("*/") &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    const n = hour.slice(2);
    return `Every ${n} hours`;
  }

  // Every N minutes: "*/N * * * *"
  if (
    minute !== undefined && minute.startsWith("*/") &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    const n = minute.slice(2);
    return `Every ${n} minutes`;
  }

  // Daily at HH:MM
  if (
    minute !== undefined && hour !== undefined &&
    !minute.includes("*") &&
    !minute.includes("/") &&
    !hour.includes("*") &&
    !hour.includes("/") &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return `Daily at ${hour.padStart(2, "0")}:${minute.padStart(2, "0")} UTC`;
  }

  return cron;
}

/** Format a timeout in minutes to a human-readable string. */
function formatTimeout(minutes: number): string {
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const rem = minutes % 60;
    if (rem === 0) return `${hours} hour${hours !== 1 ? "s" : ""}`;
    return `${hours}h ${rem}m`;
  }
  return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
}

/** Format a duration in seconds to a human-readable string. */
function formatDuration(seconds: number | null): string {
  if (seconds == null || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
}

/** Format an ISO datetime string to a short readable format. */
function formatDateTime(isoString: string | null): string {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }) + ", " + d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return isoString;
  }
}

/** Map a run status to a display color. */
function statusColor(status: string): string {
  switch (status.toLowerCase()) {
    case "success":
      return "#22c55e";
    case "failed":
    case "failure":
      return "#ef4444";
    case "running":
    case "pending":
      return "#eab308";
    case "canceled":
    case "cancelled":
    case "skipped":
      return "#9ca3af";
    default:
      return "#9ca3af";
  }
}

/** Compute wait time in seconds from queued_at to started_at. */
function computeWaitSeconds(queued: string | null, started: string | null): number | null {
  if (!queued || !started) return null;
  const diff = new Date(started).getTime() - new Date(queued).getTime();
  return diff > 0 ? Math.floor(diff / 1000) : null;
}

const PER_PAGE = 20;

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function PipelineDetail() {
  const { slug } = useParams<{ slug: string }>();
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [runs, setRuns] = useState<Run[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsPage, setRunsPage] = useState(1);
  const [runsLoading, setRunsLoading] = useState(false);

  const [artifacts, setArtifacts] = useState<ArtifactFile[]>([]);
  const [, setArtifactsLoading] = useState(false);

  const [ciJobs, setCiJobs] = useState<CIJob[]>([]);
  const [ciIncludes, setCiIncludes] = useState<CIInclude[]>([]);
  const [ciLoading, setCiLoading] = useState(false);
  const [expandedJob, setExpandedJob] = useState<number | null>(null);

  useEffect(() => {
    if (!slug) return;

    let cancelled = false;

    async function fetchPipeline() {
      setLoading(true);
      setError(null);
      setNotFound(false);

      try {
        const res = await fetch(`/api/pipelines/${encodeURIComponent(slug!)}`);

        if (!res.ok) {
          if (res.status === 404) {
            if (!cancelled) setNotFound(true);
          } else {
            if (!cancelled) setError(`Server returned ${res.status}`);
          }
          if (!cancelled) setLoading(false);
          return;
        }

        const data: Pipeline = await res.json();
        if (!cancelled) {
          setPipeline(data);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch pipeline");
          setLoading(false);
        }
      }
    }

    void fetchPipeline();

    return () => {
      cancelled = true;
    };
  }, [slug]);

  /* Fetch run history (separate from pipeline detail) */
  useEffect(() => {
    if (!slug) return;

    let cancelled = false;

    async function fetchRuns() {
      setRunsLoading(true);
      try {
        const res = await fetch(
          `/api/pipelines/${encodeURIComponent(slug!)}/runs?page=${runsPage}&per_page=${PER_PAGE}`
        );
        if (res.ok) {
          const data: RunsResponse = await res.json();
          if (!cancelled) {
            setRuns(data.runs);
            setRunsTotal(data.total);
          }
        }
      } catch {
        /* silently ignore — run history is non-critical */
      } finally {
        if (!cancelled) setRunsLoading(false);
      }
    }

    void fetchRuns();

    return () => {
      cancelled = true;
    };
  }, [slug, runsPage]);

  /* Fetch artifacts for the latest run */
  const fetchArtifacts = useCallback(async () => {
    if (!slug) return;
    setArtifactsLoading(true);
    try {
      const res = await fetch(`/api/pipelines/${encodeURIComponent(slug)}/artifacts/latest`);
      if (res.ok) {
        const data: ArtifactListResponse = await res.json();
        setArtifacts(data.artifacts ?? []);
      }
    } catch {
      /* non-critical */
    } finally {
      setArtifactsLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void fetchArtifacts();
  }, [fetchArtifacts]);

  const fetchCIDefinition = useCallback(async () => {
    if (!slug) return;
    setCiLoading(true);
    try {
      const res = await fetch(`/api/pipelines/${encodeURIComponent(slug)}/ci-jobs`);
      if (res.ok) {
        const data: CIDefinitionResponse = await res.json();
        setCiJobs(data.jobs ?? []);
        setCiIncludes(data.includes ?? []);
      }
    } catch {
      /* non-critical */
    } finally {
      setCiLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void fetchCIDefinition();
  }, [fetchCIDefinition]);

  /* ---------- Loading ---------- */
  if (loading) {
    return (
      <div>
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading pipeline...</div>
      </div>
    );
  }

  /* ---------- 404 ---------- */
  if (notFound) {
    return (
      <div>
        <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Status Board
        </Link>
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <div className="font-semibold mb-1">Pipeline not found</div>
          <div className="text-sm">
            No pipeline with slug &ldquo;{slug}&rdquo; exists.
          </div>
        </div>
      </div>
    );
  }

  /* ---------- Error ---------- */
  if (error || !pipeline) {
    return (
      <div>
        <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Status Board
        </Link>
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <div className="font-semibold mb-1">Error loading pipeline</div>
          <div className="text-sm">{error ?? "Unknown error"}</div>
        </div>
      </div>
    );
  }

  /* ---------- Render ---------- */
  const hasSkills = pipeline.skills && pipeline.skills.length > 0;
  const hasSharedLibs = pipeline.shared_libs && pipeline.shared_libs.length > 0;
  const hasJiraContracts = pipeline.jira_contracts && pipeline.jira_contracts.length > 0;
  const hasImages = pipeline.images && pipeline.images.length > 0;
  const hasTelemetryConfig = pipeline.telemetry_config && pipeline.telemetry_config.length > 0;
  const hasArtifactConfig = pipeline.artifact_config && pipeline.artifact_config.length > 0;

  return (
    <div>
      {/* Back link */}
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
        &larr; Back to Status Board
      </Link>

      {/* Header */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{pipeline.name}</h1>
        {pipeline.health && <HealthDot health={pipeline.health} size={14} />}
        {pipeline.status && (
          <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
            {pipeline.status}
          </span>
        )}
        {pipeline.platform && (
          <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
            {pipeline.platform}
          </span>
        )}
      </div>

      {/* Overview panel */}
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {pipeline.repo_url && (
            <div>
              <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Repository</div>
              <div className="text-sm text-gray-900 dark:text-gray-100 break-all">
                <a href={pipeline.repo_url} target="_blank" rel="noopener noreferrer">
                  {pipeline.repo_url}
                </a>
              </div>
            </div>
          )}
          {pipeline.owner && (
            <div>
              <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Owner</div>
              <div className="text-sm text-gray-900 dark:text-gray-100">{pipeline.owner}</div>
            </div>
          )}
          <div>
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Schedule</div>
            <div className="text-sm text-gray-900 dark:text-gray-100">
              {pipeline.cron ? humanCron(pipeline.cron) : "On demand"}
            </div>
          </div>
          {pipeline.timeout_minutes != null && pipeline.timeout_minutes > 0 && (
            <div>
              <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Timeout</div>
              <div className="text-sm text-gray-900 dark:text-gray-100">
                {formatTimeout(pipeline.timeout_minutes)}
              </div>
            </div>
          )}
        </div>
        {pipeline.description && (
          <div className="text-sm text-gray-500 dark:text-gray-400 mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">{pipeline.description}</div>
        )}
      </div>

      {/* Run History */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Run History</h2>

        {/* Charts — duration + success rate side by side */}
        {runs.length >= 2 && (() => {
          const sorted = [...runs]
            .filter((r) => r.duration_seconds != null && r.duration_seconds > 0)
            .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
          const maxDuration = sorted.length > 0 ? Math.max(...sorted.map((r) => r.duration_seconds!)) : 1;

          const allSorted = [...runs].sort(
            (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
          );
          const windowSize = Math.min(5, allSorted.length);
          const successRates: { label: string; rate: number }[] = [];
          for (let i = windowSize - 1; i < allSorted.length; i++) {
            const w = allSorted.slice(i - windowSize + 1, i + 1);
            const successes = w.filter((r) => r.status === "success").length;
            const rate = Math.round((successes / windowSize) * 100);
            const d = new Date(allSorted[i]!.started_at);
            successRates.push({
              label: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
              rate,
            });
          }

          return (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
              {/* Duration chart */}
              {sorted.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Run Duration</h3>
                  <div className="flex items-end gap-[2px] h-48">
                    {sorted.map((run) => (
                      <div
                        key={run.id}
                        className="flex-1 rounded-t transition-all"
                        style={{
                          height: `${(run.duration_seconds! / maxDuration) * 100}%`,
                          backgroundColor: statusColor(run.status),
                        }}
                        title={`${formatDuration(run.duration_seconds)} — ${run.status} — ${formatDateTime(run.started_at)}`}
                      />
                    ))}
                  </div>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-2">Green = success, red = failed, yellow = running</p>
                </div>
              )}

              {/* Success rate chart */}
              {successRates.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Success Rate (rolling {windowSize}-run window)</h3>
                  <div className="flex items-end gap-[2px] h-48">
                    {successRates.map((entry, i) => (
                      <div
                        key={i}
                        className="flex-1 rounded-t transition-all"
                        style={{
                          height: `${entry.rate}%`,
                          backgroundColor:
                            entry.rate >= 80
                              ? "rgba(16, 185, 129, 0.6)"
                              : entry.rate >= 50
                                ? "rgba(245, 158, 11, 0.6)"
                                : "rgba(239, 68, 68, 0.6)",
                        }}
                        title={`${entry.label}: ${entry.rate}% success`}
                      />
                    ))}
                  </div>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-2">Green &ge; 80%, amber &ge; 50%, red &lt; 50%</p>
                </div>
              )}
            </div>
          );
        })()}

        {/* Loading state */}
        {runsLoading && runs.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading run history...</div>
        )}

        {/* Empty state */}
        {!runsLoading && runs.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">No runs recorded yet.</div>
        )}

        {/* Runs table */}
        {runs.length > 0 && (
          <>
            <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
              <thead>
                <tr>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Status</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Started</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Duration</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Queued</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Ref</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Job</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Link</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Traces</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: statusColor(run.status) }}
                        title={run.status}
                      />
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{formatDateTime(run.started_at)}</td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{formatDuration(run.duration_seconds)}</td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400">{formatDuration(computeWaitSeconds(run.queued_at, run.started_at))}</td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                      <span className="inline-block text-xs font-mono px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">{run.ref}</span>
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{run.job}</td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                      {run.web_url ? (
                        <a
                          href={run.web_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary-600 dark:text-primary-400 hover:underline"
                          title="Open in CI platform"
                        >
                          &#x2197;
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                      {run.status !== "pending" && run.status !== "running" ? (
                        <Link
                          to={`/traces/${run.id}`}
                          className="text-primary-600 dark:text-primary-400 hover:underline"
                          title="View traces"
                        >
                          Traces
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            {runsTotal > PER_PAGE && (() => {
              const totalPages = Math.ceil(runsTotal / PER_PAGE);
              return (
                <div className="flex items-center justify-center gap-4 mt-4">
                  <button
                    className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    disabled={runsPage <= 1}
                    onClick={() => setRunsPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </button>
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    Page {runsPage} of {totalPages}
                  </span>
                  <button
                    className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    disabled={runsPage >= totalPages}
                    onClick={() => setRunsPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </div>
              );
            })()}
          </>
        )}
      </div>

      {/* Artifacts summary */}
      {artifacts.length > 0 && (() => {
        const ciCount = artifacts.filter((a) => a.source === "ci_job").length;
        const repoCount = artifacts.filter((a) => a.source === "data_repo").length;
        return (
          <div className="mb-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Artifacts</h2>
              <Link
                to="/artifacts"
                className="text-sm text-primary-600 dark:text-primary-400 hover:underline"
              >
                View all &rarr;
              </Link>
            </div>
            <div className="flex gap-4">
              {ciCount > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl px-4 py-3 flex-1">
                  <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{ciCount}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">CI Job Files</div>
                </div>
              )}
              {repoCount > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl px-4 py-3 flex-1">
                  <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{repoCount}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">Data Repo Files</div>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* CI Configuration */}
      {ciJobs.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">CI Configuration</h2>

          {/* Includes */}
          {ciIncludes.length > 0 && (
            <div className="flex gap-2 flex-wrap mb-3">
              {ciIncludes.map((inc) => (
                <span key={inc.id} className="text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                  {inc.include_type === "template" ? `template: ${inc.file}` : `${inc.project || ""}${inc.file ? ` → ${inc.file}` : ""}${inc.ref ? ` @${inc.ref}` : ""}`}
                </span>
              ))}
            </div>
          )}

          {/* Jobs table */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Job</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Stage</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Image</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Runner</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Extends</th>
                </tr>
              </thead>
              <tbody>
                {ciJobs.map((job) => (
                  <>
                    <tr
                      key={job.id}
                      className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                      onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                    >
                      <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-medium">
                        <div className="flex items-center gap-2">
                          {expandedJob === job.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          {job.name}
                          {job.timeout && <span className="text-xs text-gray-400 dark:text-gray-500">{job.timeout}</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400">{job.stage ?? "—"}</td>
                      <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                        {job.image ? <span className="text-xs font-mono">{job.image.split("/").pop()}</span> : "—"}
                      </td>
                      <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                        {job.tags.length > 0 ? job.tags.map((t) => (
                          <span key={t} className="inline-block text-xs font-medium px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 mr-1">{t}</span>
                        )) : "—"}
                      </td>
                      <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-500 dark:text-gray-400 text-xs font-mono">{job.extends ?? "—"}</td>
                    </tr>
                    {expandedJob === job.id && (
                      <tr key={`${job.id}-detail`}>
                        <td colSpan={5} className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-700/20">
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                            {/* Variables */}
                            {job.variables.length > 0 && (
                              <div>
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">Variables</h4>
                                <div className="space-y-1">
                                  {job.variables
                                    .filter((v) => !v.masked && v.value && !v.value.startsWith("$"))
                                    .slice(0, 15)
                                    .map((v) => (
                                      <div key={v.key} className="flex gap-2 text-xs">
                                        <span className="font-mono text-gray-600 dark:text-gray-400 flex-shrink-0">{v.key}</span>
                                        <span className="text-gray-900 dark:text-gray-100 truncate">{v.value}</span>
                                      </div>
                                    ))}
                                </div>
                              </div>
                            )}

                            {/* Scripts */}
                            {job.scripts.length > 0 && (
                              <div>
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">Scripts</h4>
                                <div className="bg-slate-900 text-slate-200 rounded-lg p-3 font-mono text-xs max-h-48 overflow-auto space-y-0.5">
                                  {job.scripts.map((s, i) => (
                                    <div key={i} className="flex gap-2">
                                      <span className="text-slate-500 flex-shrink-0 w-16">{s.phase === "before_script" ? "before" : s.phase === "after_script" ? "after" : "run"}</span>
                                      <span className="text-slate-200 break-all">{s.command.length > 200 ? s.command.slice(0, 200) + "..." : s.command}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {ciLoading && (
        <div className="mb-8 text-center py-8 text-gray-500 dark:text-gray-400 text-sm">Loading CI configuration...</div>
      )}

      {/* ---- Metadata sections ---- */}

      {/* Skills */}
      {hasSkills && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Skills</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Repository</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Branch</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Purpose</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.skills!.map((s, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <a href={s.repo_url} target="_blank" rel="noopener noreferrer">
                      {s.repo_url}
                    </a>
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{s.branch ?? "—"}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{s.purpose ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Shared Libraries */}
      {hasSharedLibs && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Shared Libraries</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Repository</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Purpose</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.shared_libs!.map((lib, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <a href={lib.repo_url} target="_blank" rel="noopener noreferrer">
                      {lib.repo_url}
                    </a>
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{lib.purpose ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Jira Contracts */}
      {hasJiraContracts && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Jira Contracts</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Project</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Labels</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.jira_contracts!.map((jc, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{jc.project}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    {jc.labels && jc.labels.length > 0
                      ? jc.labels.map((label, li) => (
                          <span key={li} className="inline-block text-xs font-medium px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 mr-1">
                            {label}
                          </span>
                        ))
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Images */}
      {hasImages && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Images</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Name</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Ref</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.images!.map((img, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{img.name}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{img.ref ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Telemetry Config */}
      {hasTelemetryConfig && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Telemetry Config</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Collector Type</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Endpoint</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Status</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.telemetry_config!.map((tc, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{tc.collector_type}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{tc.endpoint ?? "—"}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{tc.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Artifact Config */}
      {hasArtifactConfig && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Artifact Config</h2>
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Results Repo</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Status</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.artifact_config!.map((ac, i) => (
                <tr key={i}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <a href={ac.results_repo} target="_blank" rel="noopener noreferrer">
                      {ac.results_repo}
                    </a>
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{ac.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </div>
  );
}

export default PipelineDetail;
