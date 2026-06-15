import { useEffect, useState, useCallback } from "react";
import { X } from "lucide-react";

interface Summary {
  total_claims: number;
  verified: number;
  pending: number;
  supported: number;
  refuted: number;
  inconclusive: number;
  insufficient: number;
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
  explanation_category: string | null;
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

interface IssueRow {
  jira_key: string;
  total_claims: number;
  supported: number;
  refuted: number;
  insufficient: number;
  inconclusive: number;
  pending: number;
}

function renderMarkdown(md: string): string {
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, '<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mt-4 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mt-5 mb-1 pb-1 border-b border-gray-200 dark:border-gray-700">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold text-gray-900 dark:text-gray-100 mb-2">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-gray-900 dark:text-gray-100">$1</strong>')
    .replace(/^&gt; (.+)$/gm, '<blockquote class="pl-3 border-l-2 border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 italic my-1">$1</blockquote>')
    .replace(/^- `(.+)`$/gm, '<div class="ml-4 text-xs font-mono text-gray-600 dark:text-gray-400 leading-tight">• <code class="bg-gray-100 dark:bg-gray-700 px-1 rounded">$1</code></div>')
    .replace(/^- (.+)$/gm, '<div class="ml-4 text-sm text-gray-700 dark:text-gray-300 leading-tight">• $1</div>')
    .replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-700 text-xs px-1 py-0.5 rounded font-mono">$1</code>')
    .replace(/  \n/g, "<br/>")
    .replace(/\n\n/g, '<div class="h-2"></div>')
    .replace(/\n/g, "");
}

function Hallucinations() {
  const [activeTab, setActiveTab] = useState<"claims" | "issues" | "explanations">("claims");

  const [summary, setSummary] = useState<Summary | null>(null);
  const [typeBreakdown, setTypeBreakdown] = useState<TypeCount[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [claimsTotal, setClaimsTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [claimsLoading, setClaimsLoading] = useState(false);
  const [selectedClaimId, setSelectedClaimId] = useState<number | null>(null);
  const [claimDetail, setClaimDetail] = useState<Record<string, unknown> | null>(null);
  const [claimLogContent, setClaimLogContent] = useState<string | null>(null);
  const [jiraModalKeys, setJiraModalKeys] = useState<string[] | null>(null);
  const [sourceModalContent, setSourceModalContent] = useState<string | null>(null);
  const [sourceModalPath, setSourceModalPath] = useState<string | null>(null);

  // Issues tab state
  const [issues, setIssues] = useState<IssueRow[]>([]);
  const [issuesTotal, setIssuesToal] = useState(0);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issuesPage, setIssuesPage] = useState(0);
  const [issuesSort, setIssuesSort] = useState("refuted");
  const [issuesSortDir, setIssuesSortDir] = useState("desc");

  // Explanations tab state
  interface ExplanationRow {
    id: number;
    claim_id: number;
    category: string;
    explanation: string;
    sources_used: Array<{ type: string; path: string }>;
    explained_at: string;
    claim_text: string;
    claim_type: string;
    verdict: string | null;
    confidence: number | null;
    jira_keys: string[];
  }
  interface CategoryCount { category: string; count: number; }
  const [explanations, setExplanations] = useState<ExplanationRow[]>([]);
  const [explanationsTotal, setExplanationsTotal] = useState(0);
  const [explanationsLoading, setExplanationsLoading] = useState(false);
  const [explanationsPage, setExplanationsPage] = useState(0);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [selectedExplanation, setSelectedExplanation] = useState<ExplanationRow | null>(null);

  // Filters
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [excludeTypes, setExcludeTypes] = useState<Set<string>>(new Set());
  const [verdictFilter, setVerdictFilter] = useState<string>("all");
  const [jiraFilter, setJiraFilter] = useState<string>("");
  const [searchFilter, setSearchFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
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
      if (sourceFilter.trim()) params.set("source", sourceFilter.trim());
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
  }, [page, typeFilter, excludeTypes, verdictFilter, jiraFilter, searchFilter, sourceFilter, sortField, sortDir]);

  useEffect(() => {
    setLoading(true);
    void fetchSummary().finally(() => setLoading(false));
  }, [fetchSummary]);

  useEffect(() => {
    void fetchClaims();
  }, [fetchClaims]);

  const openClaimModal = async (claimId: number) => {
    setSelectedClaimId(claimId);
    setClaimDetail(null);
    setClaimLogContent(null);
    const [detailRes, logRes] = await Promise.all([
      fetch(`/api/hallucinations/claims/${claimId}`).catch(() => null),
      fetch(`/api/hallucinations/claims/${claimId}/log`).catch(() => null),
    ]);
    if (detailRes?.ok) setClaimDetail(await detailRes.json());
    if (logRes?.ok) setClaimLogContent(await logRes.text());
    else setClaimLogContent(null);
  };

  const closeClaimModal = () => {
    setSelectedClaimId(null);
    setClaimDetail(null);
    setClaimLogContent(null);
  };

  // Issues tab
  const fetchIssues = useCallback(async () => {
    setIssuesLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", "50");
      params.set("offset", String(issuesPage * 50));
      params.set("sort", issuesSort);
      params.set("sort_dir", issuesSortDir);
      const res = await fetch(`/api/hallucinations/issues?${params}`);
      if (res.ok) {
        const data = await res.json();
        setIssues(data.issues ?? []);
        setIssuesToal(data.total ?? 0);
      }
    } catch { /* ignore */ }
    finally { setIssuesLoading(false); }
  }, [issuesPage, issuesSort, issuesSortDir]);

  useEffect(() => {
    if (activeTab === "issues") void fetchIssues();
  }, [activeTab, fetchIssues]);

  const toggleIssuesSort = (field: string) => {
    if (issuesSort === field) {
      setIssuesSortDir((d) => d === "asc" ? "desc" : "asc");
    } else {
      setIssuesSort(field);
      setIssuesSortDir("desc");
    }
    setIssuesPage(0);
  };

  const issuesSortIndicator = (field: string) =>
    issuesSort === field ? (issuesSortDir === "asc" ? " ▲" : " ▼") : "";

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

  const resetFilters = () => {
    setTypeFilter("all");
    setExcludeTypes(new Set());
    setVerdictFilter("all");
    setJiraFilter("");
    setSearchFilter("");
    setSourceFilter("");
    setPage(0);
  };

  // Explanations tab
  const fetchExplanations = useCallback(async () => {
    setExplanationsLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", "50");
      params.set("offset", String(explanationsPage * 50));
      if (categoryFilter) params.set("category", categoryFilter);
      const [res, catRes] = await Promise.all([
        fetch(`/api/hallucinations/explanations?${params}`),
        fetch("/api/hallucinations/explanations/categories"),
      ]);
      if (res.ok) {
        const data = await res.json();
        setExplanations(data.explanations ?? []);
        setExplanationsTotal(data.total ?? 0);
      }
      if (catRes.ok) setCategories(await catRes.json());
    } catch { /* ignore */ }
    finally { setExplanationsLoading(false); }
  }, [explanationsPage, categoryFilter]);

  useEffect(() => {
    if (activeTab === "explanations") void fetchExplanations();
  }, [activeTab, fetchExplanations]);

  const totalPages = Math.ceil(claimsTotal / pageSize);

  if (loading) {
    return <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-1">Hallucination Detection</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Extracted factual claims from pipeline artifacts, verified against source material.
        Based on <a href="https://aclanthology.org/2025.acl-long.348.pdf" target="_blank" rel="noopener noreferrer" className="text-primary-600 dark:text-primary-400 hover:underline">Claimify</a> (Metropolitansky &amp; Larson, ACL 2025).
      </p>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 mb-6">
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
          <div className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-slate-600 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-slate-500">{summary.insufficient}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-1">Insufficient</div>
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

      {/* Tabs */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
        <button
          onClick={() => setActiveTab("claims")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
            activeTab === "claims" ? "border-primary-600 text-primary-600 dark:text-primary-400" : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700"
          }`}
        >By Claim</button>
        <button
          onClick={() => setActiveTab("issues")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
            activeTab === "issues" ? "border-primary-600 text-primary-600 dark:text-primary-400" : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700"
          }`}
        >By Issue</button>
        <button
          onClick={() => setActiveTab("explanations")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
            activeTab === "explanations" ? "border-primary-600 text-primary-600 dark:text-primary-400" : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700"
          }`}
        >Explanations</button>
      </div>

      {/* === Issues tab === */}
      {activeTab === "issues" && (
        <div>
          {issuesLoading && <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading issues...</div>}
          {!issuesLoading && issues.length === 0 && <div className="text-center py-12 text-gray-500 dark:text-gray-400">No issues with claims found.</div>}
          {!issuesLoading && issues.length > 0 && (
            <>
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-4">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      {([["jira_key", "Issue"], ["total", "Claims"], ["supported", "Supported"], ["refuted", "Refuted"], ["insufficient", "Insufficient"], ["inconclusive", "Inconclusive"], ["pending", "Pending"]] as const).map(([field, label]) => (
                        <th
                          key={field}
                          onClick={() => toggleIssuesSort(field)}
                          className={`text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 cursor-pointer hover:text-gray-900 dark:hover:text-gray-100 select-none ${field !== "jira_key" ? "text-right" : ""}`}
                        >
                          {label}{issuesSortIndicator(field)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {issues.map((row) => (
                      <tr
                        key={row.jira_key}
                        className="hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer"
                        onClick={() => { setActiveTab("claims"); setJiraFilter(row.jira_key); setPage(0); }}
                      >
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-primary-600 dark:text-primary-400 font-mono text-xs">{row.jira_key}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100 text-right">{row.total_claims}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-emerald-600 text-right">{row.supported || "—"}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-red-600 font-medium text-right">{row.refuted || "—"}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-400 text-right">{row.insufficient || "—"}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-amber-600 text-right">{row.inconclusive || "—"}</td>
                        <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-400 text-right">{row.pending || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {issuesTotal > 50 && (
                <div className="flex items-center justify-center gap-4">
                  <button onClick={() => setIssuesPage((p) => Math.max(0, p - 1))} disabled={issuesPage === 0} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 transition-all">Previous</button>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Page {issuesPage + 1} of {Math.ceil(issuesTotal / 50)}</span>
                  <button onClick={() => setIssuesPage((p) => p + 1)} disabled={issuesPage >= Math.ceil(issuesTotal / 50) - 1} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 transition-all">Next</button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* === Explanations tab === */}
      {activeTab === "explanations" && (
        <div>
          {explanationsLoading && <div className="text-center py-12 text-gray-500 dark:text-gray-400">Loading explanations...</div>}
          {!explanationsLoading && explanations.length === 0 && categories.length === 0 && (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">No explanations yet. Run the explain-claims skill to generate root-cause analyses.</div>
          )}
          {!explanationsLoading && categories.length > 0 && (
            <>
              {/* Category distribution bar */}
              <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 mb-6">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Explanations by Category</div>
                {(() => {
                  const catTotal = categories.reduce((s, c) => s + c.count, 0);
                  const catColors = ["bg-purple-500", "bg-indigo-500", "bg-pink-500", "bg-teal-500", "bg-orange-500", "bg-cyan-500", "bg-rose-500", "bg-lime-500"];
                  return (
                    <>
                      <div className="flex h-3 rounded-full overflow-hidden mb-3">
                        {categories.map((cat, i) => (
                          <div
                            key={cat.category}
                            className={catColors[i % catColors.length]}
                            style={{ width: `${(cat.count / catTotal) * 100}%` }}
                            title={`${cat.category}: ${cat.count}`}
                          />
                        ))}
                      </div>
                      <div className="flex gap-3 flex-wrap">
                        {categories.map((cat, i) => (
                          <button
                            key={cat.category}
                            onClick={() => { setCategoryFilter(categoryFilter === cat.category ? "" : cat.category); setExplanationsPage(0); }}
                            className={`text-xs flex items-center gap-1.5 cursor-pointer ${categoryFilter === cat.category ? "font-bold" : ""}`}
                          >
                            <span className={`inline-block w-2.5 h-2.5 rounded-full ${catColors[i % catColors.length]}`} />
                            <span className="text-gray-700 dark:text-gray-300">{cat.category}</span>
                            <span className="text-gray-400">{cat.count}</span>
                          </button>
                        ))}
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* Explanations table */}
              {explanations.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden mb-4">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-36">Category</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">Claim</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-24">Verdict</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-20">Issues</th>
                        <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-28">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {explanations.map((exp) => (
                        <tr
                          key={exp.id}
                          className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                          onClick={() => setSelectedExplanation(exp)}
                        >
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                            <span className="inline-block text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                              {exp.category}
                            </span>
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                            <span className="text-xs text-gray-400 mr-1">#{exp.claim_id}</span>
                            {exp.claim_text.length > 100 ? exp.claim_text.slice(0, 100) + "..." : exp.claim_text}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                            {exp.verdict ? (
                              <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${VERDICT_CLASSES[exp.verdict] ?? ""}`}>
                                {exp.verdict}
                              </span>
                            ) : (
                              <span className="text-xs text-gray-400">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                            {exp.jira_keys.length > 0 ? (
                              <span className="text-xs font-mono text-primary-600 dark:text-primary-400">{exp.jira_keys.join(", ")}</span>
                            ) : (
                              <span className="text-xs text-gray-400">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400">
                            {new Date(exp.explained_at).toLocaleDateString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Explanation detail modal */}
              {selectedExplanation && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setSelectedExplanation(null)}>
                  <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
                    {/* Header */}
                    <div className="flex items-center justify-between px-6 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Explanation — Claim #{selectedExplanation.claim_id}</span>
                        <span className="inline-block text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                          {selectedExplanation.category}
                        </span>
                        {selectedExplanation.verdict && (
                          <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${VERDICT_CLASSES[selectedExplanation.verdict] ?? ""}`}>
                            {selectedExplanation.verdict}
                          </span>
                        )}
                      </div>
                      <button onClick={() => setSelectedExplanation(null)} className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"><X size={18} /></button>
                    </div>

                    {/* Body */}
                    <div className="flex-1 overflow-y-auto p-6 space-y-5">
                      <div>
                        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Claim</div>
                        <div className="text-sm text-gray-900 dark:text-gray-100 leading-relaxed">{selectedExplanation.claim_text}</div>
                      </div>

                      <div>
                        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Root Cause Explanation</div>
                        <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed bg-gray-50 dark:bg-gray-700/30 border border-gray-200 dark:border-gray-700 rounded-lg p-4">{selectedExplanation.explanation}</div>
                      </div>

                      {selectedExplanation.sources_used?.length > 0 && (
                        <div>
                          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Sources Used</div>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedExplanation.sources_used.map((src, j) => (
                              <span key={j} className="text-xs font-mono px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                <span className="font-semibold text-gray-700 dark:text-gray-300">{src.type}</span>: {src.path.length > 60 ? "..." + src.path.slice(-60) : src.path}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {selectedExplanation.jira_keys.length > 0 && (
                        <div>
                          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Jira Keys</div>
                          <div className="flex gap-1.5 flex-wrap">
                            {selectedExplanation.jira_keys.map((jk) => (
                              <button
                                key={jk}
                                onClick={() => { setJiraFilter(jk); setPage(0); setActiveTab("claims"); setSelectedExplanation(null); }}
                                className="text-xs font-mono px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-primary-600 dark:text-primary-400 hover:underline cursor-pointer"
                              >
                                {jk}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-2 gap-4 text-sm border-t border-gray-200 dark:border-gray-700 pt-4">
                        <div>
                          <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Confidence</div>
                          <div className="text-gray-900 dark:text-gray-100">{selectedExplanation.confidence != null ? `${selectedExplanation.confidence}%` : "—"}</div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Explained At</div>
                          <div className="text-gray-900 dark:text-gray-100">{new Date(selectedExplanation.explained_at).toLocaleString()}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Pagination */}
              {explanationsTotal > 50 && (
                <div className="flex items-center justify-center gap-4">
                  <button onClick={() => setExplanationsPage((p) => Math.max(0, p - 1))} disabled={explanationsPage === 0} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 transition-all">Previous</button>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Page {explanationsPage + 1} of {Math.ceil(explanationsTotal / 50)}</span>
                  <button onClick={() => setExplanationsPage((p) => p + 1)} disabled={explanationsPage >= Math.ceil(explanationsTotal / 50) - 1} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 disabled:opacity-50 transition-all">Next</button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* === Claims tab === */}
      {activeTab === "claims" && (<>

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
          placeholder="Source file..."
          value={sourceFilter}
          onChange={(e) => { setSourceFilter(e.target.value); setPage(0); }}
          className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 w-[200px]"
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

        {(typeFilter !== "all" || excludeTypes.size > 0 || verdictFilter !== "all" || jiraFilter || searchFilter || sourceFilter) && (
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
                {([["claim", "Claim", ""], ["type", "Type", " w-28"], ["verdict", "Verdict", " w-24"], ["confidence", "Conf", " w-16"], ["jira", "Issues", " w-16"], ["sources", "Sources", " w-16"]] as const).map(([field, label, width]) => (
                  <th
                    key={field}
                    onClick={() => toggleSort(field)}
                    className={`text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 cursor-pointer hover:text-gray-900 dark:hover:text-gray-100 select-none${width}`}
                  >
                    {label}{sortIndicator(field)}
                  </th>
                ))}
                <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 w-28">Category</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                  onClick={() => void openClaimModal(c.id)}
                >
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100">
                    <span className="text-xs text-gray-400 dark:text-gray-600 mr-1.5">#{c.id}</span>
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
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center text-xs text-primary-600 dark:text-primary-400">
                    {c.jira_keys.length || "—"}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center text-xs text-gray-500 dark:text-gray-400">
                    {c.sources.length}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-center">
                    {c.explanation_category ? (
                      <span className="inline-block text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                        {c.explanation_category}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Claim detail modal */}
      {selectedClaimId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={closeClaimModal}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-6xl h-[92vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Claim #{selectedClaimId}</span>
                {claimDetail && (
                  <>
                    <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${TYPE_CLASSES[(claimDetail.claim_type as string)] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                      {claimDetail.claim_type as string}
                    </span>
                    {(() => {
                      const firstVerdict = ((claimDetail.verdicts as Array<Record<string, unknown>>) ?? [])[0];
                      if (!firstVerdict) return null;
                      const v = firstVerdict.verdict as string;
                      return (
                        <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${VERDICT_CLASSES[v] ?? ""}`}>
                          {v}
                        </span>
                      );
                    })()}
                  </>
                )}
              </div>
              <button onClick={closeClaimModal} className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"><X size={18} /></button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-6">
              {!claimDetail && <div className="text-sm text-gray-400">Loading...</div>}
              {claimDetail && (
                <div className="space-y-6">
                  {/* Claim text */}
                  <div>
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Claim</div>
                    <div className="text-sm text-gray-900 dark:text-gray-100 leading-relaxed">{claimDetail.claim_text as string}</div>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Sources */}
                    <div>
                      <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Sources ({(claimDetail.sources as Array<Record<string, string>>)?.length ?? 0})</div>
                      <div className="space-y-2">
                        {((claimDetail.sources as Array<Record<string, string>>) ?? []).map((s, i) => (
                          <div key={i} className="text-xs text-gray-600 dark:text-gray-400">
                            <button
                              onClick={() => void viewSourceFile(s.source_file ?? "")}
                              className="font-mono text-primary-600 dark:text-primary-400 hover:underline cursor-pointer text-left"
                            >
                              {s.source_file}
                            </button>
                            {s.original_text && (
                              <div className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 italic">
                                {(s.original_text as string).length > 300 ? (s.original_text as string).slice(0, 300) + "..." : s.original_text}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Jira keys */}
                      {((claimDetail.jira_keys as string[]) ?? []).length > 0 && (
                        <div className="mt-4">
                          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Jira Keys</div>
                          <div className="flex gap-1 flex-wrap">
                            {(claimDetail.jira_keys as string[]).map((jk) => (
                              <button
                                key={jk}
                                onClick={() => { setJiraFilter(jk); setPage(0); closeClaimModal(); }}
                                className="text-xs font-mono px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-primary-600 dark:text-primary-400 hover:underline cursor-pointer"
                              >
                                {jk}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Verdict detail */}
                    <div>
                      {((claimDetail.verdicts as Array<Record<string, unknown>>) ?? []).length > 0 ? (
                        <>
                          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Verdict</div>
                          {(claimDetail.verdicts as Array<Record<string, unknown>>).map((v, i) => (
                            <div key={i} className="space-y-2">
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
                                <div className="text-xs pl-3 border-l-2 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 font-mono whitespace-pre-wrap">
                                  {String(v.evidence_detail)}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </>
                      ) : (
                        <div className="text-xs text-gray-400 dark:text-gray-500">Not yet verified</div>
                      )}
                    </div>
                  </div>

                  {/* Explanation */}
                  {((claimDetail.explanations as Array<Record<string, unknown>>) ?? []).length > 0 && (
                    <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
                      <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Root Cause Explanation</div>
                      {(claimDetail.explanations as Array<Record<string, unknown>>).map((exp, i) => (
                        <div key={i} className="bg-gray-50 dark:bg-gray-700/30 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                          <div className="flex items-center gap-2 mb-3">
                            <span className="inline-block text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                              {exp.category as string}
                            </span>
                            <span className="text-xs text-gray-400">{new Date(exp.explained_at as string).toLocaleDateString()}</span>
                          </div>
                          <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed">{exp.explanation as string}</div>
                          {(exp.sources_used as Array<{type: string; path: string}>)?.length > 0 && (
                            <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-600">
                              <div className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Sources Used</div>
                              <div className="flex flex-wrap gap-1.5">
                                {(exp.sources_used as Array<{type: string; path: string}>).map((src, j) => (
                                  <span key={j} className="text-xs font-mono px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400">
                                    <span className="font-semibold text-gray-700 dark:text-gray-300">{src.type}</span>: {src.path.length > 50 ? "..." + src.path.slice(-50) : src.path}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Verification log */}
                  <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
                    <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Verification Log</div>
                    {claimLogContent ? (
                      <div className="bg-gray-50 dark:bg-gray-700/30 border border-gray-200 dark:border-gray-700 rounded-lg p-5">
                        <div className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed" dangerouslySetInnerHTML={{ __html: renderMarkdown(claimLogContent) }} />
                      </div>
                    ) : (
                      <div className="text-xs text-gray-400 dark:text-gray-500 italic">No verification log available for this claim.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
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
                    onClick={() => { setJiraFilter(jk); setPage(0); closeClaimModal(); setJiraModalKeys(null); }}
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

      </>)}
    </div>
  );
}

export default Hallucinations;
