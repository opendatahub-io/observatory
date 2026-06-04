import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PackageEntry {
  name: string;
  manager: string;
  versions: string[];
  pipelines: string[];
}

interface ContainerEntry {
  image_ref: string;
  digests: string[];
  pipelines: string[];
}

interface PackagesResponse {
  packages: PackageEntry[];
}

interface ContainersResponse {
  containers: ContainerEntry[];
}

type Tab = "packages" | "containers";
type ManagerFilter = "all" | "pip" | "rpm" | "npm";
type SortDir = "asc" | "desc";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Truncate a sha256 digest for display: "sha256:abc123..." -> "sha256:abc123.." */
function truncateDigest(digest: string): string {
  if (digest.startsWith("sha256:") && digest.length > 19) {
    return digest.slice(0, 19) + "...";
  }
  return digest.length > 16 ? digest.slice(0, 16) + "..." : digest;
}

/** Get the Tailwind classes for a package manager badge. */
function managerBadgeClass(manager: string): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  switch (manager.toLowerCase()) {
    case "pip":
      return `${base} bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300`;
    case "rpm":
      return `${base} bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300`;
    case "npm":
      return `${base} bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300`;
    default:
      return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300`;
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function Provenance() {
  const [activeTab, setActiveTab] = useState<Tab>("packages");

  /* Package state */
  const [packages, setPackages] = useState<PackageEntry[]>([]);
  const [pkgLoading, setPkgLoading] = useState(true);
  const [pkgError, setPkgError] = useState<string | null>(null);
  const [pkgSearch, setPkgSearch] = useState("");
  const [pkgManagerFilter, setPkgManagerFilter] = useState<ManagerFilter>("all");
  const [pkgSortDir, setPkgSortDir] = useState<SortDir>("asc");

  /* Container state */
  const [containers, setContainers] = useState<ContainerEntry[]>([]);
  const [ctrLoading, setCtrLoading] = useState(true);
  const [ctrError, setCtrError] = useState<string | null>(null);
  const [ctrSearch, setCtrSearch] = useState("");
  const [ctrSortDir, setCtrSortDir] = useState<SortDir>("asc");

  /* Clipboard feedback */
  const [copiedDigest, setCopiedDigest] = useState<string | null>(null);

  /* ---------- Fetch packages ---------- */

  const fetchPackages = useCallback(async () => {
    setPkgLoading(true);
    setPkgError(null);

    try {
      const res = await fetch("/api/provenance/packages");
      if (!res.ok) {
        setPkgError(`API returned ${res.status}: ${res.statusText}`);
        return;
      }
      const data: PackagesResponse = await res.json();
      setPackages(data.packages ?? []);
    } catch {
      setPkgError("Failed to fetch package data. The API may be unavailable.");
    } finally {
      setPkgLoading(false);
    }
  }, []);

  /* ---------- Fetch containers ---------- */

  const fetchContainers = useCallback(async () => {
    setCtrLoading(true);
    setCtrError(null);

    try {
      const res = await fetch("/api/provenance/containers");
      if (!res.ok) {
        setCtrError(`API returned ${res.status}: ${res.statusText}`);
        return;
      }
      const data: ContainersResponse = await res.json();
      setContainers(data.containers ?? []);
    } catch {
      setCtrError("Failed to fetch container data. The API may be unavailable.");
    } finally {
      setCtrLoading(false);
    }
  }, []);

  /* ---------- Initial fetch ---------- */

  useEffect(() => {
    void fetchPackages();
    void fetchContainers();
  }, [fetchPackages, fetchContainers]);

  /* ---------- Filtered & sorted packages ---------- */

  const filteredPackages = packages
    .filter((pkg) => {
      if (pkgManagerFilter !== "all" && pkg.manager.toLowerCase() !== pkgManagerFilter) {
        return false;
      }
      if (pkgSearch && !pkg.name.toLowerCase().includes(pkgSearch.toLowerCase())) {
        return false;
      }
      return true;
    })
    .sort((a, b) => {
      const cmp = a.name.localeCompare(b.name);
      return pkgSortDir === "asc" ? cmp : -cmp;
    });

  /* ---------- Filtered & sorted containers ---------- */

  const filteredContainers = containers
    .filter((ctr) => {
      if (ctrSearch && !ctr.image_ref.toLowerCase().includes(ctrSearch.toLowerCase())) {
        return false;
      }
      return true;
    })
    .sort((a, b) => {
      const cmp = a.image_ref.localeCompare(b.image_ref);
      return ctrSortDir === "asc" ? cmp : -cmp;
    });

  /* ---------- Copy digest to clipboard ---------- */

  const copyDigest = async (digest: string) => {
    try {
      await navigator.clipboard.writeText(digest);
      setCopiedDigest(digest);
      setTimeout(() => setCopiedDigest(null), 1500);
    } catch {
      // Clipboard API may not be available in some contexts
    }
  };

  /* ---------- Toggle sort ---------- */

  const togglePkgSort = () => {
    setPkgSortDir((d) => (d === "asc" ? "desc" : "asc"));
  };

  const toggleCtrSort = () => {
    setCtrSortDir((d) => (d === "asc" ? "desc" : "asc"));
  };

  /* ---------- Render pipeline links ---------- */

  const renderPipelineLinks = (pipelines: string[]) => {
    if (!pipelines || pipelines.length === 0) return "—";
    return pipelines.map((name, i) => (
      <Link
        key={i}
        to={`/pipelines/${encodeURIComponent(name)}`}
        className="text-primary-600 dark:text-primary-400 hover:underline text-sm mr-2"
      >
        {name}
      </Link>
    ));
  };

  /* ---------- Render ---------- */

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Provenance Explorer</h1>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Trace the lineage of packages and container images across pipelines.
        Identify version drift and supply-chain dependencies.
      </p>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        <button
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors cursor-pointer ${activeTab === "packages" ? "border-primary-600 text-primary-600 dark:text-primary-400" : ""}`}
          onClick={() => setActiveTab("packages")}
        >
          Packages
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors cursor-pointer ${activeTab === "containers" ? "border-primary-600 text-primary-600 dark:text-primary-400" : ""}`}
          onClick={() => setActiveTab("containers")}
        >
          Containers
        </button>
      </div>

      {/* ============================================================ */}
      {/*  PACKAGES TAB                                                 */}
      {/* ============================================================ */}
      {activeTab === "packages" && (
        <>
          {/* Loading */}
          {pkgLoading && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading package inventory...</div>
          )}

          {/* Error */}
          {!pkgLoading && pkgError && (
            <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
              <p className="font-semibold mb-1">Failed to load packages</p>
              <p className="text-sm">{pkgError}</p>
              <button
                className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer"
                onClick={() => void fetchPackages()}
              >
                Retry
              </button>
            </div>
          )}

          {/* Empty (after successful fetch with 0 results) */}
          {!pkgLoading && !pkgError && packages.length === 0 && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              <p className="font-semibold mb-1">No packages found</p>
              <p className="text-sm">
                No package provenance data has been collected yet.
              </p>
            </div>
          )}

          {/* Data */}
          {!pkgLoading && !pkgError && packages.length > 0 && (
            <>
              {/* Toolbar */}
              <div className="flex gap-3 flex-wrap items-center mb-4">
                <input
                  type="text"
                  className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 dark:focus:border-primary-500 min-w-[180px] flex-1"
                  placeholder="Search packages..."
                  value={pkgSearch}
                  onChange={(e) => setPkgSearch(e.target.value)}
                />
                <div className="flex gap-0">
                  {(["all", "pip", "rpm", "npm"] as ManagerFilter[]).map((f) => (
                    <button
                      key={f}
                      className={`text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all ${pkgManagerFilter === f ? "bg-primary-600 text-white border-primary-600" : ""}`}
                      onClick={() => setPkgManagerFilter(f)}
                    >
                      {f === "all" ? "All" : f.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              <div className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                {filteredPackages.length} package{filteredPackages.length !== 1 ? "s" : ""}
              </div>

              {filteredPackages.length === 0 ? (
                <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                  No packages match the current filters.
                </div>
              ) : (
                <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                  <thead>
                    <tr>
                      <th
                        className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 cursor-pointer"
                        onClick={togglePkgSort}
                      >
                        Package Name
                        <span className="ml-1 text-gray-400">
                          {pkgSortDir === "asc" ? "▲" : "▼"}
                        </span>
                      </th>
                      <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Manager</th>
                      <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Versions</th>
                      <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Pipelines</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPackages.map((pkg) => {
                      const hasDrift = pkg.versions.length > 1;
                      return (
                        <tr key={`${pkg.name}-${pkg.manager}`}>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{pkg.name}</td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className={managerBadgeClass(pkg.manager)}>
                              {pkg.manager}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className={hasDrift ? "text-amber-600 dark:text-amber-400 font-medium" : ""}>
                              {pkg.versions.join(", ")}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{renderPipelineLinks(pkg.pipelines)}</td>
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

      {/* ============================================================ */}
      {/*  CONTAINERS TAB                                               */}
      {/* ============================================================ */}
      {activeTab === "containers" && (
        <>
          {/* Loading */}
          {ctrLoading && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading container inventory...</div>
          )}

          {/* Error */}
          {!ctrLoading && ctrError && (
            <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
              <p className="font-semibold mb-1">Failed to load containers</p>
              <p className="text-sm">{ctrError}</p>
              <button
                className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer"
                onClick={() => void fetchContainers()}
              >
                Retry
              </button>
            </div>
          )}

          {/* Empty */}
          {!ctrLoading && !ctrError && containers.length === 0 && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              <p className="font-semibold mb-1">No containers found</p>
              <p className="text-sm">
                No container provenance data has been collected yet.
              </p>
            </div>
          )}

          {/* Data */}
          {!ctrLoading && !ctrError && containers.length > 0 && (
            <>
              {/* Toolbar */}
              <div className="flex gap-3 flex-wrap items-center mb-4">
                <input
                  type="text"
                  className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 dark:focus:border-primary-500 min-w-[180px] flex-1"
                  placeholder="Search images..."
                  value={ctrSearch}
                  onChange={(e) => setCtrSearch(e.target.value)}
                />
              </div>

              <div className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                {filteredContainers.length} container{filteredContainers.length !== 1 ? "s" : ""}
              </div>

              {filteredContainers.length === 0 ? (
                <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                  No containers match the current search.
                </div>
              ) : (
                <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                  <thead>
                    <tr>
                      <th
                        className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 cursor-pointer"
                        onClick={toggleCtrSort}
                      >
                        Image Ref
                        <span className="ml-1 text-gray-400">
                          {ctrSortDir === "asc" ? "▲" : "▼"}
                        </span>
                      </th>
                      <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Digests</th>
                      <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Pipelines</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredContainers.map((ctr) => (
                      <tr key={ctr.image_ref}>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{ctr.image_ref}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                          {ctr.digests.length === 0
                            ? "—"
                            : ctr.digests.map((digest, i) => (
                                <div key={i} className="flex items-center gap-2 mb-1">
                                  <span
                                    className="font-mono text-xs text-gray-600 dark:text-gray-400"
                                    title={digest}
                                  >
                                    {truncateDigest(digest)}
                                  </span>
                                  <button
                                    className="text-xs text-primary-600 dark:text-primary-400 hover:underline cursor-pointer bg-transparent border-none"
                                    onClick={() => void copyDigest(digest)}
                                    title="Copy full digest"
                                  >
                                    {copiedDigest === digest ? (
                                      <span className="text-xs text-emerald-600 dark:text-emerald-400">Copied</span>
                                    ) : (
                                      "Copy"
                                    )}
                                  </button>
                                </div>
                              ))}
                        </td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{renderPipelineLinks(ctr.pipelines)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default Provenance;
