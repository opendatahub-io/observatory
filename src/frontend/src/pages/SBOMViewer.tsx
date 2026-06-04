import { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SBOMDocument {
  image_ref?: string;
  digest?: string;
  format?: string;
  generator?: string;
  generated_at?: string;
  document?: {
    spdxVersion?: string;
    name?: string;
    packages?: SpdxPackage[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface SpdxPackage {
  name: string;
  versionInfo?: string;
  SPDXID?: string;
  supplier?: string;
  downloadLocation?: string;
  [key: string]: unknown;
}

interface Vulnerability {
  id: string;
  severity: string;
  package?: string;
  installed_version?: string;
  fixed_version?: string;
  description?: string;
  [key: string]: unknown;
}

interface VulnerabilitiesResponse {
  vulnerabilities: Vulnerability[];
}

type SeverityLevel = "critical" | "high" | "medium" | "low" | "negligible" | "unknown";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function normalizeSeverity(severity: string): SeverityLevel {
  const s = severity.toLowerCase().trim();
  if (s === "critical") return "critical";
  if (s === "high") return "high";
  if (s === "medium") return "medium";
  if (s === "low") return "low";
  if (s === "negligible") return "negligible";
  return "unknown";
}

function severityBadgeClass(severity: string): string {
  const level = normalizeSeverity(severity);
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  const map: Record<SeverityLevel, string> = {
    critical: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    high: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
    medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
    low: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
    negligible: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
    unknown: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  };
  return `${base} ${map[level]}`;
}

function severityColor(severity: string): string {
  const level = normalizeSeverity(severity);
  const map: Record<SeverityLevel, string> = {
    critical: "#dc2626",
    high: "#ea580c",
    medium: "#ca8a04",
    low: "#2563eb",
    negligible: "#6b7280",
    unknown: "#6b7280",
  };
  return map[level];
}

function formatDate(isoString: string | undefined): string {
  if (!isoString) return "--";
  try {
    const d = new Date(isoString);
    return d.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function SBOMViewer() {
  const { digest } = useParams<{ digest: string }>();

  const [sbom, setSbom] = useState<SBOMDocument | null>(null);
  const [vulns, setVulns] = useState<Vulnerability[]>([]);
  const [loading, setLoading] = useState(true);
  const [vulnLoading, setVulnLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vulnError, setVulnError] = useState<string | null>(null);

  const fetchSbom = useCallback(async () => {
    if (!digest) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`/api/sboms/${encodeURIComponent(digest)}`);
      if (!res.ok) {
        if (res.status === 404) {
          setError("No SBOM found for this digest.");
        } else {
          setError(`API returned ${res.status}: ${res.statusText}`);
        }
        return;
      }
      const data: SBOMDocument = await res.json();
      setSbom(data);
    } catch {
      setError("Failed to fetch SBOM data. The API may be unavailable.");
    } finally {
      setLoading(false);
    }
  }, [digest]);

  const fetchVulnerabilities = useCallback(async () => {
    if (!digest) return;
    setVulnLoading(true);
    setVulnError(null);

    try {
      const res = await fetch(`/api/sboms/${encodeURIComponent(digest)}/vulnerabilities`);
      if (!res.ok) {
        if (res.status === 404) {
          setVulns([]);
        } else {
          setVulnError(`API returned ${res.status}: ${res.statusText}`);
        }
        return;
      }
      const data: VulnerabilitiesResponse = await res.json();
      setVulns(data.vulnerabilities ?? []);
    } catch {
      setVulnError("Failed to fetch vulnerability data.");
    } finally {
      setVulnLoading(false);
    }
  }, [digest]);

  useEffect(() => {
    void fetchSbom();
    void fetchVulnerabilities();
  }, [fetchSbom, fetchVulnerabilities]);

  /* Derive packages from SBOM SPDX document */
  const packages: SpdxPackage[] =
    sbom?.document?.packages?.filter(
      (p) => p.name && p.SPDXID !== "SPDXRef-DOCUMENT"
    ) ?? [];

  /* Vulnerability counts by severity */
  const vulnCounts: Record<string, number> = {};
  for (const v of vulns) {
    const level = normalizeSeverity(v.severity);
    vulnCounts[level] = (vulnCounts[level] ?? 0) + 1;
  }

  /* ---------- Loading ---------- */
  if (loading) {
    return (
      <div>
        <Link to="/provenance" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Provenance
        </Link>
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading SBOM...</div>
      </div>
    );
  }

  /* ---------- Error ---------- */
  if (error) {
    return (
      <div>
        <Link to="/provenance" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
          &larr; Back to Provenance
        </Link>
        <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
          <p className="font-semibold mb-1">Failed to load SBOM</p>
          <p className="text-sm">{error}</p>
          <button className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer" onClick={() => void fetchSbom()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Back link */}
      <Link to="/provenance" className="text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 mb-4 inline-block">
        &larr; Back to Provenance
      </Link>

      {/* Header */}
      <div className="flex justify-between items-center mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">SBOM Viewer</h1>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Software Bill of Materials for the selected container image.
      </p>

      {/* Metadata */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {sbom?.image_ref && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Image Ref</div>
            <div className="text-sm text-gray-900 dark:text-gray-100 break-all">{sbom.image_ref}</div>
          </div>
        )}
        {digest && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Digest</div>
            <div className="text-sm text-gray-900 dark:text-gray-100 break-all">{digest}</div>
          </div>
        )}
        {sbom?.format && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Format</div>
            <div className="text-sm text-gray-900 dark:text-gray-100 break-all">{sbom.format}</div>
          </div>
        )}
        {sbom?.generator && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Generator</div>
            <div className="text-sm text-gray-900 dark:text-gray-100 break-all">{sbom.generator}</div>
          </div>
        )}
        {sbom?.generated_at && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Generated</div>
            <div className="text-sm text-gray-900 dark:text-gray-100 break-all">{formatDate(sbom.generated_at)}</div>
          </div>
        )}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Total Packages</div>
          <div className="text-2xl font-bold" style={{ color: "var(--color-text)" }}>
            {packages.length}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Critical</div>
          <div className="text-2xl font-bold" style={{ color: severityColor("critical") }}>
            {vulnCounts.critical ?? 0}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">High</div>
          <div className="text-2xl font-bold" style={{ color: severityColor("high") }}>
            {vulnCounts.high ?? 0}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Medium</div>
          <div className="text-2xl font-bold" style={{ color: severityColor("medium") }}>
            {vulnCounts.medium ?? 0}
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Low</div>
          <div className="text-2xl font-bold" style={{ color: severityColor("low") }}>
            {vulnCounts.low ?? 0}
          </div>
        </div>
      </div>

      {/* Packages section */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Packages ({packages.length})</h2>
        {packages.length === 0 ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            <p className="font-semibold mb-1 text-gray-900 dark:text-gray-100">No packages</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No package entries found in the SBOM document.
            </p>
          </div>
        ) : (
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Package Name</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Version</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Supplier</th>
              </tr>
            </thead>
            <tbody>
              {packages.map((pkg, i) => (
                <tr key={pkg.SPDXID ?? `${pkg.name}-${i}`}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{pkg.name}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{pkg.versionInfo ?? "--"}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{pkg.supplier ?? "--"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Vulnerabilities section */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">
          Vulnerabilities ({vulns.length})
        </h2>

        {vulnLoading && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading vulnerabilities...</div>
        )}

        {!vulnLoading && vulnError && (
          <div className="text-center p-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800">
            <p className="font-semibold mb-1">Failed to load vulnerabilities</p>
            <p className="text-sm">{vulnError}</p>
            <button
              className="mt-3 text-sm px-4 py-1.5 rounded-lg border border-red-200 dark:border-red-700 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer"
              onClick={() => void fetchVulnerabilities()}
            >
              Retry
            </button>
          </div>
        )}

        {!vulnLoading && !vulnError && vulns.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            <p className="font-semibold mb-1 text-gray-900 dark:text-gray-100">No vulnerabilities</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No vulnerability data found for this image.
            </p>
          </div>
        )}

        {!vulnLoading && !vulnError && vulns.length > 0 && (
          <table className="w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Vuln ID</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Severity</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Package</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Installed</th>
                <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Fixed</th>
              </tr>
            </thead>
            <tbody>
              {vulns.map((v, i) => (
                <tr key={`${v.id}-${i}`}>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{v.id}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <span className={severityBadgeClass(v.severity)}>
                      {v.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{v.package ?? "--"}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{v.installed_version ?? "--"}</td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">{v.fixed_version ?? "--"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default SBOMViewer;
