import { useEffect, useState, useCallback } from "react";
import { ChevronRight, ChevronDown, X } from "lucide-react";

interface Summary {
  total_claims: number;
  verified: number;
  pending: number;
  supported: number;
  refuted: number;
  inconclusive: number;
  jira_keys_referenced: number;
}

interface TypeCount {
  claim_type: string;
  count: number;
}

interface ClaimVerdict {
  verdict: string;
  confidence: number;
  evidence_summary: string;
  evidence_source: string | null;
}

interface ClaimSource {
  pipeline_slug: string;
  source_file: string;
}

interface Claim {
  id: number;
  claim_text: string;
  claim_type: string;
  claim_hash: string;
  jira_keys: string[];
  sources: ClaimSource[];
  verdict: ClaimVerdict | null;
}

interface ClaimsResponse {
  claims: Claim[];
  total: number;
}

const VERDICT_CLASSES: Record<string, string> = {
  supported: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  refuted: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  inconclusive: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  insufficient: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
};

const TYPE_CLASSES: Record<string, string> = {
  factual: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  architectural: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  security: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  scope: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  attribution: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
};

function Hallucinations() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [typeBreakdown, setTypeBreakdown] = useState<TypeCount[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [claimsTotal, setClaimsTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [claimsLoading, setClaimsLoading] = useState(false);
  const [expandedClaim, setExpandedClaim] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<Record<string, unknown> | null>(null);
  const [jiraModalKeys, setJiraModalKeys] = useState<string[] | null>(null);
  const [logModalContent, setLogModalContent] = useState<string | null>(null);
  const [logModalClaimId, setLogModalClaimId] = useState<number | null>(null);
  const [sourceModalContent, setSourceModalContent] = useState<string | null>(null);
  const [sourceModalPath, setSourceModalPath] = useState<string | null>(null);

  // Filters
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [excludeTypes, setExcludeTypes] = useState<Set<string>>(new Set());
  const [verdictFilter, setVerdictFilter] = useState<string>("all");
  const [jiraFilter, setJiraFilter] = useState<string>("");
  const [searchFilter, setSearchFilter] = useState<string>("");
  const [page, setPage] = useState(0);

  // Sorting
  type SortField = "claim" | "type" | "verdict" | "confidence" | "jira" | "sources";
  type SortDir = "asc" | "desc";
  const [sortField, setSortField] = useState<SortField>("jira");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const sortIndicator = (field: SortField) =>
    sortField === field ? (sortDir === "asc" ? " ▲" : " ▼") : "";
  const pageSize = 25;

  const fetchSummary = useCallback(async () => {
    try {
      const [sumRes, typeRes] = await Promise.all([
        fetch("/api/hallucinations/summary"),
        fetch("/api/hallucinations/by-type"),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (typeRes.ok) setTypeBreakdown(await typeRes.json());
    } catch { /* ignore */ }
  }, []);

  const fetchClaims = useCallback(async () => {
    setClaimsLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(page * pageSize));
      if (typeFilter !== "all") params.set("type", typeFilter);
      if (excludeTypes.size > 0) params.set("exclude_types", [...excludeTypes].join(","));
      if (verdictFilter !== "all") params.set("verdict", verdictFilter);
      if (jiraFilter.trim()) params.set("jira_key", jiraFilter.trim());
      if (searchFilter.trim()) params.set("search", searchFilter.trim());
      params.set("sort", sortField);
      params.set("sort_dir", sortDir);

      const res = await fetch(`/api/hallucinations/claims?${params}`);
      if (res.ok) {
        const data: ClaimsResponse = await res.json();
        setClaims(data.claims);
        setClaimsTotal(data.total);
      }
    } catch { /* ignore */ }
    finally { setClaimsLoading(false); }
  }, [page, typeFilter, excludeTypes, verdictFilter, jiraFilter, searchFilter, sortField, sortDir]);

  useEffect(() => {
    setLoading(true);
    void fetchSummary().finally(() => setLoading(false));
  }, [fetchSummary]);

  useEffect(() => {
    void fetchClaims();
  }, [fetchClaims]);

  const toggleClaim = async (claimId: number) => {
    if (expandedClaim === claimId) {
      setExpandedClaim(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedClaim(claimId);
    setExpandedDetail(null);
    try {
      const res = await fetch(`/api/hallucinations/claims/${claimId}`);
      if (res.ok) setExpandedDetail(await res.json());
    } catch { /* ignore */ }
  };

  const viewSourceFile = async (path: string) => {
    setSourceModalPath(path);
    setSourceModalContent(null);
    try {
      const res = await fetch(`/api/hallucinations/source-file?path=${encodeURIComponent(path)}`);
      if (res.ok) {
        setSourceModalContent(await res.text());
      } else {
        setSourceModalContent("_Source file not available._");
      }
    } catch {
      setSourceModalContent("_Failed to load source file._");
    }
  };

  const viewLog = async (claimId: number) => {
    setLogModalClaimId(claimId);
    setLogModalContent(null);
    try {
      const res = await fetch(`/api/hallucinations/claims/${claimId}/log`);
      if (res.ok) {
        setLogModalContent(await res.text());
      } else {
        setLogModalContent("_Verification log not available for this claim._");
      }
    } catch {
      setLogModalContent("_Failed to load verification log._");
    }
  };

  const resetFilters = () => {
    setTypeFilter("all");
    setExcludeTypes(new Set());
    setVerdictFilter("all");
    setJiraFilter("");
    setSearchFilter("");
    setPage(0);
  };

  const totalPages = Math.ceil(claimsTotal / pageSize);

  if (loading) {
    return <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-1">Hallucination Detection</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Extracted factual claims from pipeline artifacts, verified against source material.
      </p>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.total_claims.toLocaleString()}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Claims</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.verified.toLocaleString()}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Verified</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.pending.toLocaleString()}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Pending</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{summary.supported}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Supported</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-red-200 dark:border-red-800 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-red-600">{summary.refuted}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Refuted</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-amber-200 dark:border-amber-800 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-amber-600">{summary.inconclusive}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Inconclusive</div>
          </div>
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.jira_keys_referenced}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Jira Keys</div>
          </div>
        </div>
      )}

      {/* Type breakdown bar */}
      {typeBreakdown.length > 0 && (() => {
        const total = typeBreakdown.reduce((s, t) => s + t.count, 0);
        return (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 mb-6">
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Claims by Type</div>
            <div className="flex h-3 rounded-full overflow-hidden mb-3">
              {typeBreakdown.map((t) => {
                const colors: Record<string, string> = { factual: "bg-blue-500", architectural: "bg-violet-500", security: "bg-red-500", scope: "bg-amber-500", attribution: "bg-emerald-500" };
                return (
                  <div
                    key={t.claim_type}
                    className={colors[t.claim_type] ?? "bg-gray-400"}
                    style={{ width: `${(t.count / total) * 100}%` }}
                    title={`${t.claim_type}: ${t.count.toLocaleString()}`}
                  />
                );
              })}
            </div>
            <div className="flex gap-4 flex-wrap">
              {typeBreakdown.map((t) => (
                <button
                  key={t.claim_type}
                  onClick={(e) => {
                    setPage(0);
                    if (e.shiftKey) {
                      setExcludeTypes((prev) => {
                        const next = new Set(prev);
                        if (next.has(t.claim_type)) next.delete(t.claim_type);
                        else next.add(t.claim_type);
                        return next;
                      });
                      setTypeFilter("all");
                    } else {
                      setTypeFilter(typeFilter === t.claim_type ? "all" : t.claim_type);
                      setExcludeTypes(new Set());
                    }
                  }}
                  className={`text-xs flex items-center gap-1.5 cursor-pointer ${typeFilter === t.claim_type ? "font-bold" : ""} ${excludeTypes.has(t.claim_type) ? "opacity-30 line-through" : ""}`}
                >
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${TYPE_CLASSES[t.claim_type] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                    {t.claim_type}
                  </span>
                  <span className="text-gray-500 dark:text-gray-400">{t.count.toLocaleString()}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Filters */}
      <div className="flex gap-3 flex-wrap items-center mb-4">
        <input
          type="text"
          placeholder="Search claims..."
          value={searchFilter}
          onChange={(e) => { setSearchFilter(e.target.value); setPage(0); }}
          className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 flex-1 min-w-[200px]"
        />

        <input
          type="text"
          placeholder="Jira key"
          value={jiraFilter}
          onChange={(e) => { setJiraFilter(e.target.value); setPage(0); }}
          className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 w-[180px]"
        />

        <select
          value={verdictFilter}
          onChange={(e) => { setVerdictFilter(e.target.value); setPage(0); }}
          className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
        >
          <option value="all">All verdicts</option>
          <option value="pending">Pending</option>
          <option value="supported">Supported</option>
          <option value="refuted">Refuted</option>
          <option value="inconclusive">Inconclusive</option>
          <option value="insufficient">Insufficient</option>
        </select>

        {(typeFilter !== "all" || excludeTypes.size > 0 || verdictFilter !== "all" || jiraFilter || searchFilter) && (
          <button onClick={resetFilters} className="text-xs text-primary-600 dark:text-primary-400 hover:underline">
            Clear filters
          </button>
        )}

        <span className="text-sm text-gray-500 dark:text-gray-400 ml-auto">
          {claimsTotal.toLocaleString()} claims
        </span>
      </div>

      {/* Claims table */}
      {claimsLoading && claims.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading claims...</div>
      )}

      {!claimsLoading && claims.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">No claims match the current filters.</div>
      )}

      {claims.length > 0 && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-4">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="px-4 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-8"></th>
                {([["claim", "Claim", ""], ["type", "Type", " w-28"], ["verdict", "Verdict", " w-24"], ["confidence", "Conf", " w-16"], ["jira", "Issues", " w-16"], ["sources", "Sources", " w-16"]] as const).map(([field, label, width]) => (
                  <th
                    key={field}
                    onClick={() => toggleSort(field)}
                    className={`text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 cursor-pointer hover:text-gray-900 dark:hover:text-gray-100 select-none${width}`}
                  >
                    {label}{sortIndicator(field)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <>
                  <tr
                    key={c.id}
                    className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                    onClick={() => void toggleClaim(c.id)}
                  >
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                      {expandedClaim === c.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                      {c.claim_text.length > 120 ? c.claim_text.slice(0, 120) + "..." : c.claim_text}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                      <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${TYPE_CLASSES[c.claim_type] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                        {c.claim_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                      {c.verdict ? (
                        <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${VERDICT_CLASSES[c.verdict.verdict] ?? ""}`}>
                          {c.verdict.verdict}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400 dark:text-gray-500">pending</span>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center text-xs">
                      {c.verdict ? (
                        <span className={c.verdict.confidence >= 80 ? "text-gray-900 dark:text-gray-100 font-medium" : c.verdict.confidence >= 50 ? "text-amber-600" : "text-red-600"}>
                          {c.verdict.confidence}%
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center">
                      {c.jira_keys.length === 0 ? (
                        <span className="text-xs text-gray-400">—</span>
                      ) : (
                        <button
                          onClick={(e) => { e.stopPropagation(); setJiraModalKeys(c.jira_keys); }}
                          className="text-xs font-medium text-primary-600 dark:text-primary-400 hover:underline cursor-pointer"
                        >
                          {c.jira_keys.length}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center text-xs text-gray-500 dark:text-gray-400">
                      {c.sources.length}
                    </td>
                  </tr>
                  {expandedClaim === c.id && (
                    <tr key={`${c.id}-detail`}>
                      <td colSpan={5} className="px-4 py-4 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-700/20">
                        {!expandedDetail && <div className="text-sm text-gray-400">Loading...</div>}
                        {expandedDetail && (
                          <div className="space-y-4">
                            {/* Full claim text */}
                            <div>
                              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Claim</div>
                              <div className="text-sm text-gray-900 dark:text-gray-100">{c.claim_text}</div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                              {/* Sources */}
                              <div>
                                <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Sources ({((expandedDetail as Record<string, unknown>).sources as Array<Record<string, string>>)?.length ?? 0})</div>
                                <div className="space-y-1">
                                  {((expandedDetail as Record<string, unknown>).sources as Array<Record<string, string>> ?? []).map((s, i) => (
                                    <div key={i} className="text-xs text-gray-600 dark:text-gray-400">
                                      <button
                                        onClick={(e) => { e.stopPropagation(); void viewSourceFile(s.source_file ?? ""); }}
                                        className="font-mono text-primary-600 dark:text-primary-400 hover:underline cursor-pointer text-left"
                                      >
                                        {s.source_file}
                                      </button>
                                      {s.original_text && (
                                        <div className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 italic">
                                          {(s.original_text as string).length > 200 ? (s.original_text as string).slice(0, 200) + "..." : s.original_text}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>

                              {/* Verdict detail */}
                              <div>
                                {((expandedDetail as Record<string, unknown>).verdicts as Array<Record<string, unknown>> ?? []).length > 0 ? (
                                  <>
                                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Verdict</div>
                                    {((expandedDetail as Record<string, unknown>).verdicts as Array<Record<string, unknown>>).map((v, i) => (
                                      <div key={i} className="space-y-1">
                                        <div className="flex items-center gap-2">
                                          <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${VERDICT_CLASSES[v.verdict as string] ?? ""}`}>
                                            {v.verdict as string}
                                          </span>
                                          <span className="text-xs text-gray-500">confidence: {v.confidence as number}%</span>
                                        </div>
                                        {v.evidence_summary ? (
                                          <div className="text-sm text-gray-700 dark:text-gray-300">{String(v.evidence_summary)}</div>
                                        ) : null}
                                        {v.evidence_detail ? (
                                          <div className="text-xs pl-3 border-l-2 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 font-mono">
                                            {String(v.evidence_detail)}
                                          </div>
                                        ) : null}
                                      </div>
                                    ))}
                                  </>
                                ) : (
                                  <div className="text-xs text-gray-400 dark:text-gray-500">Not yet verified</div>
                                )}

                                {/* Jira keys */}
                                {c.jira_keys.length > 0 && (
                                  <div className="mt-3">
                                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Jira Keys</div>
                                    <div className="flex gap-1 flex-wrap">
                                      {c.jira_keys.map((jk) => (
                                        <button
                                          key={jk}
                                          onClick={(e) => { e.stopPropagation(); setJiraFilter(jk); setPage(0); setExpandedClaim(null); }}
                                          className="text-xs font-mono px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-primary-600 dark:text-primary-400 hover:underline cursor-pointer"
                                        >
                                          {jk}
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* View log */}
                                <button
                                  onClick={(e) => { e.stopPropagation(); void viewLog(c.id); }}
                                  className="mt-3 text-xs text-primary-600 dark:text-primary-400 hover:underline cursor-pointer"
                                >
                                  View verification log
                                </button>
                              </div>
                            </div>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Jira keys modal */}
      {jiraModalKeys && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-6" onClick={() => setJiraModalKeys(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md max-h-[70vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{jiraModalKeys.length} Jira Issues</span>
              <button onClick={() => setJiraModalKeys(null)} className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"><X size={18} /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <div className="flex flex-wrap gap-2">
                {jiraModalKeys.sort().map((jk) => (
                  <button
                    key={jk}
                    onClick={() => { setJiraFilter(jk); setPage(0); setExpandedClaim(null); setJiraModalKeys(null); }}
                    className="text-xs font-mono px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-700 text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/30 cursor-pointer transition-colors"
                  >
                    {jk}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Verification log modal */}
      {logModalClaimId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-6" onClick={() => { setLogModalClaimId(null); setLogModalContent(null); }}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-5xl h-[90vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Verification Log — Claim {logModalClaimId}</span>
              <button onClick={() => { setLogModalClaimId(null); setLogModalContent(null); }} className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"><X size={18} /></button>
            </div>
            <div className="flex-1 overflow-auto p-5">
              {!logModalContent && <div className="text-sm text-gray-400">Loading...</div>}
              {logModalContent && (
                <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-words leading-relaxed">{logModalContent}</pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Source file modal */}
      {sourceModalPath && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-6" onClick={() => { setSourceModalPath(null); setSourceModalContent(null); }}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-5xl h-[90vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{sourceModalPath}</span>
              <button onClick={() => { setSourceModalPath(null); setSourceModalContent(null); }} className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg flex-shrink-0 ml-3"><X size={18} /></button>
            </div>
            <div className="flex-1 overflow-auto p-5">
              {!sourceModalContent && <div className="text-sm text-gray-400">Loading...</div>}
              {sourceModalContent && (
                <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-words leading-relaxed">{sourceModalContent}</pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export default Hallucinations;
