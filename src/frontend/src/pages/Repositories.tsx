import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type RepoKind = "pipeline_source" | "skill" | "shared_lib" | "results";
type RepoStatus = "active" | "inactive" | "archived";

interface Repository {
  id: number;
  domain: string;
  owner: string;
  name: string;
  kind: RepoKind;
  git_url: string;
  description: string | null;
  status: RepoStatus;
  default_branch: string;
  checkout_path: string;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
}

interface LinkedPipeline {
  pipeline_id: number;
  slug: string;
  name: string;
  relation: string;
  purpose: string | null;
  branch: string | null;
}

interface RepositoryDetail extends Repository {
  linked_pipelines: LinkedPipeline[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function timeAgo(dateString: string | null): string {
  if (!dateString) return "Never";
  const then = new Date(dateString).getTime();
  if (isNaN(then)) return "Invalid date";
  const diffMs = Date.now() - then;
  if (diffMs < 0) return "Just now";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return seconds <= 1 ? "Just now" : `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 min ago" : `${minutes} mins ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

const KIND_LABELS: Record<RepoKind, string> = {
  pipeline_source: "Pipeline Source",
  skill: "Skill",
  shared_lib: "Shared Lib",
  results: "Results",
};

type SyncLevel = "green" | "red" | "grey";

function syncLevel(repo: Repository): SyncLevel {
  if (repo.last_sync_status === "error") return "red";
  if (repo.last_sync_status === "ok") return "green";
  return "grey";
}

const SYNC_DOT: Record<SyncLevel, string> = {
  green: "bg-emerald-500",
  red: "bg-red-500",
  grey: "bg-gray-400",
};

const SYNC_LABEL: Record<SyncLevel, string> = {
  green: "Synced",
  red: "Failed",
  grey: "Never synced",
};

const BTN =
  "text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer";
const BTN_PRIMARY = `${BTN} !bg-primary-600 !text-white !border-primary-600 hover:!bg-primary-700`;
const TH =
  "text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700";
const TD =
  "px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100";
const LBL = "block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1";
const INP =
  "w-full text-sm px-2.5 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400";

interface AddForm {
  git_url: string;
  domain: string;
  owner: string;
  name: string;
  kind: RepoKind;
  default_branch: string;
  description: string;
}

const EMPTY_ADD_FORM: AddForm = {
  git_url: "",
  domain: "",
  owner: "",
  name: "",
  kind: "pipeline_source",
  default_branch: "main",
  description: "",
};

/**
 * Parse a git URL into { domain, owner, name }, mirroring the backend
 * parse_repo_url() (HTTPS + SCP-style SSH, nested GitLab subgroups). Returns
 * null if it can't extract all three parts.
 */
function parseRepoUrl(url: string): { domain: string; owner: string; name: string } | null {
  const raw = url.trim();
  if (!raw) return null;
  let domain: string;
  let path: string;
  const afterAt = raw.includes("@") ? raw.split("@").slice(1).join("@") : "";
  if (!raw.includes("://") && afterAt && afterAt.includes(":")) {
    // SCP-style: git@host:owner/repo.git
    const [host, ...rest] = afterAt.split(":");
    domain = host;
    path = rest.join(":");
  } else {
    try {
      const u = new URL(raw);
      domain = u.hostname;
      path = u.pathname;
    } catch {
      return null;
    }
  }
  path = path.replace(/^\/+|\/+$/g, "");
  if (path.endsWith(".git")) path = path.slice(0, -4);
  const parts = path.split("/").filter(Boolean);
  if (!domain || parts.length < 2) return null;
  return { domain, owner: parts.slice(0, -1).join("/"), name: parts[parts.length - 1] };
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function Repositories() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<RepoKind | "all">("all");
  const [statusFilter, setStatusFilter] = useState<RepoStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState<Set<number>>(new Set());
  const [flash, setFlash] = useState<{ id: number; msg: string; ok: boolean } | null>(null);
  const [detail, setDetail] = useState<RepositoryDetail | null>(null);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  // Add-repository form
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState<AddForm>(EMPTY_ADD_FORM);
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const fetchRepos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/repositories");
      if (!res.ok) {
        setError(`API returned ${res.status}: ${res.statusText}`);
        return;
      }
      setRepos((await res.json()) as Repository[]);
    } catch {
      setError("Failed to reach the repositories API.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRepos();
  }, [fetchRepos]);

  const syncRepo = async (id: number) => {
    setSyncing((prev) => new Set(prev).add(id));
    setFlash(null);
    try {
      const res = await fetch(`/api/v1/repositories/${id}/sync`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (res.ok && body.status === "ok") {
        setFlash({ id, msg: "Synced", ok: true });
      } else {
        setFlash({ id, msg: body.error ? `Failed: ${body.error}` : "Sync failed", ok: false });
      }
    } catch {
      setFlash({ id, msg: "Sync failed (network error)", ok: false });
    } finally {
      setSyncing((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      void fetchRepos();
    }
  };

  const openDetail = async (id: number) => {
    try {
      const res = await fetch(`/api/v1/repositories/${id}`);
      if (res.ok) setDetail((await res.json()) as RepositoryDetail);
    } catch {
      /* ignore */
    }
  };

  // Auto-fill domain/owner/name as the user types/pastes a git URL. Fields stay
  // editable afterward — parsing only overwrites while they still match a prior
  // parse (so manual edits are preserved).
  const onUrlChange = (git_url: string) => {
    setAddForm((prev) => {
      const parsed = parseRepoUrl(git_url);
      const prevParsed = parseRepoUrl(prev.git_url);
      const untouched =
        !prevParsed ||
        (prev.domain === prevParsed.domain &&
          prev.owner === prevParsed.owner &&
          prev.name === prevParsed.name);
      if (parsed && untouched) return { ...prev, git_url, ...parsed };
      return { ...prev, git_url };
    });
  };

  const openAdd = () => {
    setAddForm(EMPTY_ADD_FORM);
    setAddError(null);
    setShowAdd(true);
  };

  const createRepo = async () => {
    setAddBusy(true);
    setAddError(null);
    const payload = {
      domain: addForm.domain.trim(),
      owner: addForm.owner.trim(),
      name: addForm.name.trim(),
      kind: addForm.kind,
      git_url: addForm.git_url.trim(),
      default_branch: addForm.default_branch.trim() || "main",
      description: addForm.description.trim() || null,
    };
    if (!payload.git_url || !payload.domain || !payload.owner || !payload.name) {
      setAddError("git_url is required and must parse into domain / owner / name.");
      setAddBusy(false);
      return;
    }
    try {
      const res = await fetch("/api/v1/repositories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 201) {
        setShowAdd(false);
        await fetchRepos();
      } else if (res.status === 409) {
        setAddError("A repository with this domain / owner / name already exists.");
      } else {
        const body = await res.json().catch(() => ({}));
        setAddError(body.detail ? String(body.detail) : `API returned ${res.status}.`);
      }
    } catch {
      setAddError("Failed to reach the repositories API.");
    } finally {
      setAddBusy(false);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return repos.filter((r) => {
      if (kindFilter !== "all" && r.kind !== kindFilter) return false;
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (q) {
        const hay = `${r.domain}/${r.owner}/${r.name}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [repos, kindFilter, statusFilter, search]);

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-start mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Repositories</h1>
        <div className="flex items-center gap-2">
          <button className={BTN_PRIMARY} onClick={openAdd}>
            + Add Repository
          </button>
          <button className={BTN} onClick={() => void fetchRepos()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Git repositories referenced by pipelines (source, skills, shared libraries),
        checked out under <code>/checkouts</code> for the chat agent to read.
        The registry is derived from pipeline metadata and synced automatically;
        use <strong>Sync</strong> to force a fresh checkout.
      </p>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap items-center mb-4">
        <select
          className="text-sm px-2.5 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-primary-400"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value as RepoKind | "all")}
        >
          <option value="all">All kinds</option>
          <option value="pipeline_source">Pipeline Source</option>
          <option value="skill">Skill</option>
          <option value="shared_lib">Shared Lib</option>
          <option value="results">Results</option>
        </select>
        <select
          className="text-sm px-2.5 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-primary-400"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as RepoStatus | "all")}
        >
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="archived">Archived</option>
        </select>
        <input
          type="text"
          className="text-sm px-2.5 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 min-w-[220px]"
          placeholder="Search domain/owner/name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-sm text-gray-400 dark:text-gray-500">
          {filtered.length} of {repos.length}
        </span>
      </div>

      {loading && repos.length === 0 && !error && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading repositories...</div>
      )}

      {error && (
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load repositories</p>
          <p className="text-sm">{error}</p>
          <button className={BTN} onClick={() => void fetchRepos()} style={{ marginTop: 12 }}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && repos.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          No repositories registered yet. They are populated from pipeline metadata,
          or add one manually with <strong>+ Add Repository</strong>.
        </div>
      )}

      {filtered.length > 0 && (
        <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-6">
          <thead>
            <tr>
              <th className={TH}>Sync</th>
              <th className={TH}>Repository</th>
              <th className={TH}>Kind</th>
              <th className={TH}>Status</th>
              <th className={TH}>Last Synced</th>
              <th className={TH}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((repo) => {
              const level = syncLevel(repo);
              const isSyncing = syncing.has(repo.id);
              return (
                <tr key={repo.id}>
                  <td className={TD}>
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${SYNC_DOT[level]}`}
                        title={SYNC_LABEL[level]}
                      />
                      {repo.last_sync_status === "error" && repo.last_sync_error ? (
                        <span
                          className="text-red-600 dark:text-red-400 text-xs cursor-pointer hover:underline"
                          onClick={() => setExpandedError(repo.last_sync_error)}
                        >
                          {SYNC_LABEL[level]}
                        </span>
                      ) : (
                        <span className="text-xs">{SYNC_LABEL[level]}</span>
                      )}
                    </div>
                  </td>
                  <td className={TD}>
                    <button
                      className="text-left hover:underline text-primary-700 dark:text-primary-400"
                      onClick={() => void openDetail(repo.id)}
                      title="View linked pipelines"
                    >
                      <span className="text-gray-400 dark:text-gray-500">{repo.domain}/</span>
                      {repo.owner}/<strong>{repo.name}</strong>
                    </button>
                  </td>
                  <td className={TD}>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                      {KIND_LABELS[repo.kind]}
                    </span>
                  </td>
                  <td className={TD}>
                    <span
                      className={
                        repo.status === "active"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-gray-400 dark:text-gray-500"
                      }
                    >
                      {repo.status}
                    </span>
                  </td>
                  <td className={TD}>{timeAgo(repo.last_synced_at)}</td>
                  <td className={TD}>
                    <div className="flex items-center gap-2">
                      <button
                        className={BTN_PRIMARY}
                        onClick={() => void syncRepo(repo.id)}
                        disabled={isSyncing}
                      >
                        {isSyncing ? "Syncing..." : "Sync"}
                      </button>
                      {flash && flash.id === repo.id && (
                        <span
                          className={`text-xs font-medium ${
                            flash.ok
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-red-600 dark:text-red-400"
                          }`}
                        >
                          {flash.msg}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Detail modal: linked pipelines */}
      {detail && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => setDetail(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-2xl w-full mx-4 p-6 max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">
              {detail.domain}/{detail.owner}/{detail.name}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-1 break-all">
              {detail.git_url}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-4 break-all">
              Checkout: <code>{detail.checkout_path}</code>
            </div>

            <div className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
              Linked pipelines ({detail.linked_pipelines.length})
            </div>
            {detail.linked_pipelines.length === 0 ? (
              <div className="text-sm text-gray-400 dark:text-gray-500 mb-4">
                Not linked to any pipeline.
              </div>
            ) : (
              <table className="w-full text-sm mb-4">
                <thead>
                  <tr>
                    <th className={TH}>Pipeline</th>
                    <th className={TH}>Relation</th>
                    <th className={TH}>Branch</th>
                    <th className={TH}>Purpose</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.linked_pipelines.map((lp) => (
                    <tr key={`${lp.pipeline_id}-${lp.relation}`}>
                      <td className={TD}>
                        <Link
                          to={`/pipelines/${encodeURIComponent(lp.slug)}`}
                          className="text-primary-700 dark:text-primary-400 hover:underline"
                          onClick={() => setDetail(null)}
                        >
                          {lp.name}
                        </Link>
                      </td>
                      <td className={TD}>{lp.relation}</td>
                      <td className={TD}>{lp.branch || "-"}</td>
                      <td className={TD}>{lp.purpose || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <button className={BTN} onClick={() => setDetail(null)}>
              Close
            </button>
          </div>
        </div>
      )}

      {/* Sync error modal */}
      {expandedError && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => setExpandedError(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full mx-4 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">
              Last Sync Error
            </div>
            <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap mb-4 max-h-64 overflow-y-auto font-mono">
              {expandedError}
            </div>
            <button className={BTN} onClick={() => setExpandedError(null)}>
              Close
            </button>
          </div>
        </div>
      )}

      {/* Add repository modal */}
      {showAdd && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => !addBusy && setShowAdd(false)}
        >
          <form
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full mx-4 p-6 max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              void createRepo();
            }}
          >
            <div className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">
              Add Repository
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
              Manually register a repo. Paste a git URL; domain / owner / name are
              parsed automatically and remain editable. Repos referenced by pipeline
              metadata are registered automatically — this is for the rest.
            </p>

            <label className={LBL}>Git URL</label>
            <input
              className={INP}
              autoFocus
              placeholder="https://gitlab.com/group/subgroup/repo.git"
              value={addForm.git_url}
              onChange={(e) => onUrlChange(e.target.value)}
            />

            <div className="grid grid-cols-3 gap-2 mt-3">
              <div>
                <label className={LBL}>Domain</label>
                <input
                  className={INP}
                  placeholder="gitlab.com"
                  value={addForm.domain}
                  onChange={(e) => setAddForm((p) => ({ ...p, domain: e.target.value }))}
                />
              </div>
              <div>
                <label className={LBL}>Owner</label>
                <input
                  className={INP}
                  placeholder="group/subgroup"
                  value={addForm.owner}
                  onChange={(e) => setAddForm((p) => ({ ...p, owner: e.target.value }))}
                />
              </div>
              <div>
                <label className={LBL}>Name</label>
                <input
                  className={INP}
                  placeholder="repo"
                  value={addForm.name}
                  onChange={(e) => setAddForm((p) => ({ ...p, name: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 mt-3">
              <div>
                <label className={LBL}>Kind</label>
                <select
                  className={INP}
                  value={addForm.kind}
                  onChange={(e) => setAddForm((p) => ({ ...p, kind: e.target.value as RepoKind }))}
                >
                  <option value="pipeline_source">Pipeline Source</option>
                  <option value="skill">Skill</option>
                  <option value="shared_lib">Shared Lib</option>
                  <option value="results">Results</option>
                </select>
              </div>
              <div>
                <label className={LBL}>Default branch</label>
                <input
                  className={INP}
                  placeholder="main"
                  value={addForm.default_branch}
                  onChange={(e) => setAddForm((p) => ({ ...p, default_branch: e.target.value }))}
                />
              </div>
            </div>

            <label className={`${LBL} mt-3`}>Description (optional)</label>
            <input
              className={INP}
              value={addForm.description}
              onChange={(e) => setAddForm((p) => ({ ...p, description: e.target.value }))}
            />

            {addError && (
              <div className="mt-3 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2 border border-red-200 dark:border-red-800">
                {addError}
              </div>
            )}

            <div className="flex items-center gap-2 mt-5">
              <button type="submit" className={BTN_PRIMARY} disabled={addBusy}>
                {addBusy ? "Adding..." : "Add Repository"}
              </button>
              <button
                type="button"
                className={BTN}
                onClick={() => setShowAdd(false)}
                disabled={addBusy}
              >
                Cancel
              </button>
              <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">
                Sync it after adding to fetch a checkout.
              </span>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export default Repositories;
