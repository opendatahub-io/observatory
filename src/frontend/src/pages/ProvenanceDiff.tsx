import { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Run {
  id: number;
  external_id: string;
  job: string;
  started_at: string;
  status: string;
  ref: string;
}

interface RunsResponse {
  runs: Run[];
  total: number;
}

interface ProvenancePackage {
  name: string;
  version?: string;
  manager?: string;
}

interface ProvenanceContainer {
  image_ref: string;
  digest?: string;
}

interface ProvenanceCommand {
  command: string;
  step?: string;
}

interface ProvenanceData {
  packages?: ProvenancePackage[];
  containers?: ProvenanceContainer[];
  commands?: ProvenanceCommand[];
  [key: string]: unknown;
}

/* Diff entry types */
interface PackageDiff {
  name: string;
  change: "added" | "removed" | "changed";
  versionA?: string;
  versionB?: string;
  manager?: string;
}

interface ContainerDiff {
  image_ref: string;
  change: "added" | "removed" | "changed";
  digestA?: string;
  digestB?: string;
}

interface CommandDiff {
  command: string;
  change: "added" | "removed" | "changed";
  commandA?: string;
  commandB?: string;
  step?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDateTime(isoString: string | null): string {
  if (!isoString) return "--";
  try {
    const d = new Date(isoString);
    return (
      d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
      ", " +
      d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
    );
  } catch {
    return isoString;
  }
}

function changeBadgeClass(change: "added" | "removed" | "changed"): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  const map = {
    added: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    removed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    changed: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  };
  return `${base} ${map[change]}`;
}

function diffRowClass(change: "added" | "removed" | "changed"): string {
  const map = {
    added: "bg-emerald-50/50 dark:bg-emerald-900/10",
    removed: "bg-red-50/50 dark:bg-red-900/10",
    changed: "bg-amber-50/50 dark:bg-amber-900/10",
  };
  return map[change];
}

function computePackageDiff(
  pkgsA: ProvenancePackage[],
  pkgsB: ProvenancePackage[]
): PackageDiff[] {
  const mapA = new Map<string, ProvenancePackage>();
  const mapB = new Map<string, ProvenancePackage>();

  for (const p of pkgsA) mapA.set(p.name, p);
  for (const p of pkgsB) mapB.set(p.name, p);

  const diffs: PackageDiff[] = [];

  /* Removed: in A but not in B */
  for (const [name, pkg] of mapA) {
    if (!mapB.has(name)) {
      diffs.push({ name, change: "removed", versionA: pkg.version, manager: pkg.manager });
    }
  }

  /* Added: in B but not in A */
  for (const [name, pkg] of mapB) {
    if (!mapA.has(name)) {
      diffs.push({ name, change: "added", versionB: pkg.version, manager: pkg.manager });
    }
  }

  /* Changed: in both but version differs */
  for (const [name, pkgA] of mapA) {
    const pkgB = mapB.get(name);
    if (pkgB && pkgA.version !== pkgB.version) {
      diffs.push({
        name,
        change: "changed",
        versionA: pkgA.version,
        versionB: pkgB.version,
        manager: pkgA.manager,
      });
    }
  }

  return diffs.sort((a, b) => {
    const order = { removed: 0, changed: 1, added: 2 };
    const diff = order[a.change] - order[b.change];
    return diff !== 0 ? diff : a.name.localeCompare(b.name);
  });
}

function computeContainerDiff(
  ctrsA: ProvenanceContainer[],
  ctrsB: ProvenanceContainer[]
): ContainerDiff[] {
  const mapA = new Map<string, ProvenanceContainer>();
  const mapB = new Map<string, ProvenanceContainer>();

  for (const c of ctrsA) mapA.set(c.image_ref, c);
  for (const c of ctrsB) mapB.set(c.image_ref, c);

  const diffs: ContainerDiff[] = [];

  for (const [ref, ctr] of mapA) {
    if (!mapB.has(ref)) {
      diffs.push({ image_ref: ref, change: "removed", digestA: ctr.digest });
    }
  }

  for (const [ref, ctr] of mapB) {
    if (!mapA.has(ref)) {
      diffs.push({ image_ref: ref, change: "added", digestB: ctr.digest });
    }
  }

  for (const [ref, ctrA] of mapA) {
    const ctrB = mapB.get(ref);
    if (ctrB && ctrA.digest !== ctrB.digest) {
      diffs.push({
        image_ref: ref,
        change: "changed",
        digestA: ctrA.digest,
        digestB: ctrB.digest,
      });
    }
  }

  return diffs.sort((a, b) => {
    const order = { removed: 0, changed: 1, added: 2 };
    const diff = order[a.change] - order[b.change];
    return diff !== 0 ? diff : a.image_ref.localeCompare(b.image_ref);
  });
}

function computeCommandDiff(
  cmdsA: ProvenanceCommand[],
  cmdsB: ProvenanceCommand[]
): CommandDiff[] {
  const setA = new Set(cmdsA.map((c) => c.command));
  const setB = new Set(cmdsB.map((c) => c.command));

  const diffs: CommandDiff[] = [];

  for (const cmd of cmdsA) {
    if (!setB.has(cmd.command)) {
      diffs.push({ command: cmd.command, change: "removed", commandA: cmd.command, step: cmd.step });
    }
  }

  for (const cmd of cmdsB) {
    if (!setA.has(cmd.command)) {
      diffs.push({ command: cmd.command, change: "added", commandB: cmd.command, step: cmd.step });
    }
  }

  return diffs.sort((a, b) => {
    const order = { removed: 0, changed: 1, added: 2 };
    const diff = order[a.change] - order[b.change];
    return diff !== 0 ? diff : a.command.localeCompare(b.command);
  });
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function ProvenanceDiff() {
  const { slug } = useParams<{ slug: string }>();

  const [runs, setRuns] = useState<Run[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [runIdA, setRunIdA] = useState<string>("");
  const [runIdB, setRunIdB] = useState<string>("");

  const [provA, setProvA] = useState<ProvenanceData | null>(null);
  const [provB, setProvB] = useState<ProvenanceData | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [diffComputed, setDiffComputed] = useState(false);

  /* Fetch runs */
  const fetchRuns = useCallback(async () => {
    if (!slug) return;
    setRunsLoading(true);
    setRunsError(null);

    try {
      const res = await fetch(
        `/api/pipelines/${encodeURIComponent(slug)}/runs?per_page=100`
      );
      if (!res.ok) {
        setRunsError(`API returned ${res.status}: ${res.statusText}`);
        return;
      }
      const data: RunsResponse = await res.json();
      setRuns(data.runs ?? []);
    } catch {
      setRunsError("Failed to fetch runs. The API may be unavailable.");
    } finally {
      setRunsLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  /* Compare handler */
  const handleCompare = async () => {
    if (!slug || !runIdA || !runIdB) return;
    setDiffLoading(true);
    setDiffError(null);
    setDiffComputed(false);
    setProvA(null);
    setProvB(null);

    try {
      const [resA, resB] = await Promise.all([
        fetch(
          `/api/pipelines/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runIdA)}/provenance`
        ),
        fetch(
          `/api/pipelines/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runIdB)}/provenance`
        ),
      ]);

      if (!resA.ok || !resB.ok) {
        const badStatus = !resA.ok ? resA.status : resB.status;
        if (badStatus === 404) {
          setDiffError(
            "Provenance data not available for one or both selected runs."
          );
        } else {
          setDiffError(`API error: ${badStatus}`);
        }
        return;
      }

      const dataA: ProvenanceData = await resA.json();
      const dataB: ProvenanceData = await resB.json();
      setProvA(dataA);
      setProvB(dataB);
      setDiffComputed(true);
    } catch {
      setDiffError("Failed to fetch provenance data for comparison.");
    } finally {
      setDiffLoading(false);
    }
  };

  /* Compute diffs */
  const packageDiffs =
    diffComputed && provA && provB
      ? computePackageDiff(provA.packages ?? [], provB.packages ?? [])
      : [];

  const containerDiffs =
    diffComputed && provA && provB
      ? computeContainerDiff(provA.containers ?? [], provB.containers ?? [])
      : [];

  const commandDiffs =
    diffComputed && provA && provB
      ? computeCommandDiff(provA.commands ?? [], provB.commands ?? [])
      : [];

  /* Label for a run in the dropdown */
  const runLabel = (run: Run) =>
    `#${run.id} - ${run.status} - ${run.ref} (${formatDateTime(run.started_at)})`;

  /* ---------- Render ---------- */

  return (
    <div>
      {/* Back link */}
      <Link
        to={`/pipelines/${encodeURIComponent(slug ?? "")}`}
        className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block"
      >
        &larr; Back to Pipeline
      </Link>

      {/* Header */}
      <div className="flex justify-between items-center mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Provenance Diff</h1>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Compare provenance data between two pipeline runs to identify changes in
        packages, containers, and commands.
      </p>

      {/* Runs loading */}
      {runsLoading && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading runs...</div>
      )}

      {/* Runs error */}
      {!runsLoading && runsError && (
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load runs</p>
          <p className="text-sm">{runsError}</p>
        </div>
      )}

      {/* No runs */}
      {!runsLoading && !runsError && runs.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="font-semibold mb-1 text-gray-900 dark:text-gray-100">No runs available</p>
          <p className="text-sm">
            This pipeline has no recorded runs to compare.
          </p>
        </div>
      )}

      {/* Run selectors */}
      {!runsLoading && !runsError && runs.length > 0 && (
        <>
          <div className="flex gap-4 flex-wrap items-end mb-6">
            <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Run A (baseline)</label>
              <select
                className="text-sm px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
                value={runIdA}
                onChange={(e) => setRunIdA(e.target.value)}
              >
                <option value="">Select a run...</option>
                {runs.map((run) => (
                  <option key={run.id} value={String(run.id)}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Run B (compare)</label>
              <select
                className="text-sm px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
                value={runIdB}
                onChange={(e) => setRunIdB(e.target.value)}
              >
                <option value="">Select a run...</option>
                {runs.map((run) => (
                  <option key={run.id} value={String(run.id)}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </div>

            <button
              className="text-sm font-medium px-4 py-2 rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              disabled={!runIdA || !runIdB || runIdA === runIdB || diffLoading}
              onClick={() => void handleCompare()}
            >
              {diffLoading ? "Comparing..." : "Compare"}
            </button>
          </div>

          {/* Same run warning */}
          {runIdA && runIdB && runIdA === runIdB && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              Please select two different runs to compare.
            </div>
          )}

          {/* Diff error */}
          {diffError && (
            <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
              <p className="font-semibold mb-1">Comparison failed</p>
              <p className="text-sm">{diffError}</p>
            </div>
          )}

          {/* Diff loading */}
          {diffLoading && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">Fetching provenance data...</div>
          )}

          {/* Diff results */}
          {diffComputed && !diffLoading && !diffError && (
            <>
              {/* Packages diff */}
              <div className="mb-8">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">
                  Packages ({packageDiffs.length} change{packageDiffs.length !== 1 ? "s" : ""})
                </h2>
                {packageDiffs.length === 0 ? (
                  <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                    No package changes between these runs.
                  </div>
                ) : (
                  <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                    <thead>
                      <tr>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Change</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Package</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Manager</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Version (A)</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Version (B)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {packageDiffs.map((d, i) => (
                        <tr key={`${d.name}-${i}`} className={diffRowClass(d.change)}>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className={changeBadgeClass(d.change)}>
                              {d.change}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.name}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.manager ?? "--"}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.versionA ?? "--"}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.versionB ?? "--"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Containers diff */}
              <div className="mb-8">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">
                  Containers ({containerDiffs.length} change{containerDiffs.length !== 1 ? "s" : ""})
                </h2>
                {containerDiffs.length === 0 ? (
                  <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                    No container changes between these runs.
                  </div>
                ) : (
                  <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                    <thead>
                      <tr>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Change</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Image Ref</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Digest (A)</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Digest (B)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {containerDiffs.map((d, i) => (
                        <tr key={`${d.image_ref}-${i}`} className={diffRowClass(d.change)}>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className={changeBadgeClass(d.change)}>
                              {d.change}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.image_ref}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">{d.digestA ?? "--"}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">{d.digestB ?? "--"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Commands diff */}
              <div className="mb-8">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">
                  Commands ({commandDiffs.length} change{commandDiffs.length !== 1 ? "s" : ""})
                </h2>
                {commandDiffs.length === 0 ? (
                  <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
                    No command changes between these runs.
                  </div>
                ) : (
                  <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                    <thead>
                      <tr>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Change</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Command</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Step</th>
                      </tr>
                    </thead>
                    <tbody>
                      {commandDiffs.map((d, i) => (
                        <tr key={`cmd-${i}`} className={diffRowClass(d.change)}>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className={changeBadgeClass(d.change)}>
                              {d.change}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 font-mono text-xs">{d.command}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{d.step ?? "--"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default ProvenanceDiff;
