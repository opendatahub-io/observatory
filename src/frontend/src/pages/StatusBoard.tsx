import { useEffect, useState, useCallback, useMemo } from "react";
import { LayoutGrid, List } from "lucide-react";
import PipelineCard from "../components/PipelineCard";

export interface Pipeline {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  owner: string | null;
  repo_url: string | null;
  platform: string;
  group: string | null;
  display_order: number | null;
  cron: string | null;
  expected_interval_minutes: number | null;
  timeout_minutes: number | null;
  status: string;
  health: string;
  created_at: string;
  updated_at: string;
}

function StatusBoard() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [grouped, setGrouped] = useState(true);

  const fetchPipelines = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/pipelines");
      if (!res.ok) {
        throw new Error(`API returned ${res.status}: ${res.statusText}`);
      }
      const data: { pipelines: Pipeline[] } = await res.json();
      setPipelines(data.pipelines);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch pipelines");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPipelines();
  }, [fetchPipelines]);

  const filtered = pipelines
    .filter((p) => statusFilter === "all" || p.status === statusFilter)
    .filter((p) => platformFilter === "all" || p.platform === platformFilter)
    .filter((p) => {
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        p.name.toLowerCase().includes(q) ||
        (p.owner?.toLowerCase().includes(q) ?? false)
      );
    });

  const groupEntries = useMemo(() => {
    if (!grouped) return null;
    const map: Record<string, Pipeline[]> = {};
    for (const p of filtered) {
      const g = p.group || "Ungrouped";
      if (!map[g]) map[g] = [];
      map[g].push(p);
    }
    return Object.entries(map).sort(([, a], [, b]) => {
      const minA = Math.min(...a.map((p) => p.display_order ?? 9999));
      const minB = Math.min(...b.map((p) => p.display_order ?? 9999));
      return minA - minB;
    });
  }, [filtered, grouped]);

  const statuses = Array.from(new Set(pipelines.map((p) => p.status)));
  const platforms = Array.from(new Set(pipelines.map((p) => p.platform)));

  const filterBtn = (active: boolean) =>
    active
      ? "text-sm font-medium px-3 py-1.5 rounded-lg border border-primary-600 bg-primary-600 text-white cursor-pointer transition-all"
      : "text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all";

  return (
    <div>
      {/* Header row */}
      <div className="flex justify-between items-center mb-5 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
          Status Board
        </h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setGrouped((v) => !v)}
            title={grouped ? "Flat view" : "Grouped view"}
            className="p-2 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            {grouped ? <List size={18} /> : <LayoutGrid size={18} />}
          </button>
          <button
            onClick={() => void fetchPipelines()}
            disabled={loading}
            className="text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-primary-600 dark:text-primary-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex gap-3 flex-wrap items-center mb-6 p-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <input
          type="text"
          placeholder="Search name or owner..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 dark:focus:border-primary-500 min-w-[180px] flex-1"
        />

        <div className="flex gap-1 flex-wrap">
          <button onClick={() => setStatusFilter("all")} className={filterBtn(statusFilter === "all")}>
            All statuses
          </button>
          {statuses.map((s) => (
            <button key={s} onClick={() => setStatusFilter(statusFilter === s ? "all" : s)} className={filterBtn(statusFilter === s)}>
              {s}
            </button>
          ))}
        </div>

        <div className="flex gap-1 flex-wrap">
          <button onClick={() => setPlatformFilter("all")} className={filterBtn(platformFilter === "all")}>
            All platforms
          </button>
          {platforms.map((p) => (
            <button key={p} onClick={() => setPlatformFilter(platformFilter === p ? "all" : p)} className={filterBtn(platformFilter === p)}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading && pipelines.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          Loading pipelines...
        </div>
      )}

      {error && (
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load pipelines</p>
          <p className="text-sm">{error}</p>
          <button
            onClick={() => void fetchPipelines()}
            className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && pipelines.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="font-semibold mb-1">No pipelines registered</p>
          <p className="text-sm">Add pipelines through the Admin page to see them here.</p>
        </div>
      )}

      {!loading && !error && pipelines.length > 0 && filtered.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          No pipelines match the current filters.
        </div>
      )}

      {/* Grouped view */}
      {filtered.length > 0 && groupEntries && (
        <>
          {groupEntries.map(([groupName, items]) => (
            <div key={groupName} className="mb-6">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
                {groupName}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {items.map((p) => (
                  <PipelineCard key={p.id} pipeline={p} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {/* Flat view */}
      {filtered.length > 0 && !groupEntries && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((p) => (
            <PipelineCard key={p.id} pipeline={p} />
          ))}
        </div>
      )}
    </div>
  );
}

export default StatusBoard;
