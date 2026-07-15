import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { X } from "lucide-react";

import {
  buildOccurrenceParams,
  processingStateLabel,
  verdictClass,
} from "../utils/claimTriage";

interface Summary {
  total_occurrences: number;
  verified: number;
  pending: number;
  supported: number;
  contradicted: number;
  insufficient_evidence: number;
  not_applicable: number;
  explained: number;
  human_review_required: number;
  jira_keys_referenced: number;
}

interface TypeCount { claim_type: string; count: number; }

interface Occurrence {
  id: number;
  normalized_claim_id: number;
  claim_text: string;
  original_text?: string;
  claim_type: string;
  modality?: string;
  product_version?: string;
  source_file: string;
  source_locator: string;
  pipeline_slug: string;
  jira_keys: string[];
  verification_run_id?: number;
  verdict?: string;
  severity?: string;
  confidence?: number;
  evidence_summary?: string;
  explanation_run_id?: number;
  explanation_category?: string;
  improvement_target?: string;
  human_review_required?: number;
  processing_state: string;
  override_count: number;
}

interface Evidence {
  id: number;
  evidence_type: string;
  uri?: string;
  repository_revision?: string;
  artifact_digest?: string;
  source_locator?: string;
  query?: string;
  relationship?: string;
  authority?: string;
}

interface Regression {
  id: number;
  dataset_fqn: string;
  implementation_revision: string;
  status: string;
  metrics: Record<string, unknown>;
  run_uri?: string;
}

interface Explanation {
  id: number;
  verification_run_id: number;
  claim_occurrence_id?: number;
  category: string;
  improvement_target?: string;
  explanation: string;
  contributing_factors: string[];
  alternative_explanations: string[];
  remediation?: string;
  regression_test?: string;
  human_review_required: number;
  evidence: Evidence[];
  regression_runs: Regression[];
  claim_text?: string;
  claim_type?: string;
  verdict?: string;
  confidence?: number;
  jira_keys?: string[];
  source_file?: string;
  created_at?: string;
}

interface Verification {
  id: number;
  verdict: string;
  severity?: string;
  confidence: number;
  evidence_summary?: string;
  verifier_revision: string;
  repository_revision?: string;
  evidence_context_digest: string;
  created_at: string;
  evidence: Evidence[];
  explanation_runs: Explanation[];
}

interface History {
  occurrence: Occurrence & { source_unit_text?: string };
  jira_keys: string[];
  verification_runs: Verification[];
  human_overrides: Array<{
    id: number; verification_run_id: number; actor: string;
    decision: string; rationale: string; created_at: string;
  }>;
  effective_verification_run_id?: number;
  effective_explanation_run_id?: number;
  processing_state: string;
}

interface IssueRow {
  jira_key: string;
  total_occurrences: number;
  supported: number;
  contradicted: number;
  insufficient_evidence: number;
  not_applicable: number;
  pending: number;
}

interface Facet { value: string; count: number; }

const TYPE_CLASSES: Record<string, string> = {
  factual: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  architectural: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  security: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  scope: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  attribution: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
};

function Badge({ value, className = "" }: { value: string; className?: string }) {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${className || "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200"}`}>{value.replace(/_/g, " ")}</span>;
}

function Hallucinations() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<"claims" | "issues" | "explanations">("claims");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [types, setTypes] = useState<TypeCount[]>([]);
  const [occurrences, setOccurrences] = useState<Occurrence[]>([]);
  const [occurrenceTotal, setOccurrenceTotal] = useState(0);
  const [history, setHistory] = useState<History | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [typeFilter, setTypeFilter] = useState("all");
  const [verdictFilter, setVerdictFilter] = useState("all");
  const [jiraFilter, setJiraFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [sort, setSort] = useState("confidence");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [issues, setIssues] = useState<IssueRow[]>([]);
  const [explanations, setExplanations] = useState<Explanation[]>([]);
  const [explanationTotal, setExplanationTotal] = useState(0);
  const [categories, setCategories] = useState<Facet[]>([]);
  const [targets, setTargets] = useState<Facet[]>([]);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [targetFilter, setTargetFilter] = useState("");
  const [explanationJiraFilter, setExplanationJiraFilter] = useState("");
  const [humanReviewFilter, setHumanReviewFilter] = useState("all");
  const [explanationPage, setExplanationPage] = useState(0);
  const pageSize = 25;

  const loadOverview = useCallback(async () => {
    const [summaryResponse, typeResponse] = await Promise.all([
      fetch("/api/v2/claims/triage/summary"),
      fetch("/api/v2/claims/triage/types"),
    ]);
    if (!summaryResponse.ok || !typeResponse.ok) throw new Error("Claim triage API unavailable");
    setSummary(await summaryResponse.json());
    setTypes(await typeResponse.json());
  }, []);

  const loadOccurrences = useCallback(async () => {
    const query = buildOccurrenceParams({
      limit: pageSize, offset: page * pageSize, typeFilter, verdictFilter,
      jiraFilter, searchFilter, sourceFilter, sort, sortDir,
    });
    const response = await fetch(`/api/v2/claims/triage/occurrences?${query}`);
    if (!response.ok) throw new Error("Could not load claim occurrences");
    const data = await response.json();
    setOccurrences(data.occurrences ?? []);
    setOccurrenceTotal(data.total ?? 0);
  }, [page, typeFilter, verdictFilter, jiraFilter, searchFilter, sourceFilter, sort, sortDir]);

  const openOccurrence = useCallback(async (occurrenceId: number) => {
    setLoadingHistory(true);
    try {
      const response = await fetch(`/api/v2/claims/occurrences/${occurrenceId}/history`);
      if (!response.ok) throw new Error("Claim occurrence was not found");
      setHistory(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load occurrence history");
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const selectOccurrence = (occurrenceId: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("occurrence", String(occurrenceId));
    setSearchParams(next, { replace: true });
  };

  const closeHistory = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("occurrence");
    setSearchParams(next, { replace: true });
    setHistory(null);
  };

  useEffect(() => {
    Promise.all([loadOverview(), loadOccurrences()])
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [loadOverview, loadOccurrences]);

  useEffect(() => {
    const occurrence = Number(searchParams.get("occurrence"));
    if (!loadingHistory && Number.isInteger(occurrence) && occurrence > 0 && history?.occurrence.id !== occurrence) {
      void openOccurrence(occurrence);
    }
  }, [searchParams, history, loadingHistory, openOccurrence]);

  useEffect(() => {
    if (activeTab !== "issues") return;
    void fetch("/api/v2/claims/triage/issues?limit=200")
      .then((response) => response.json())
      .then((data) => setIssues(data.issues ?? []))
      .catch(() => setError("Could not load issue triage"));
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== "explanations") return;
    const params = new URLSearchParams({ limit: "50", offset: String(explanationPage * 50) });
    if (categoryFilter) params.set("category", categoryFilter);
    if (targetFilter) params.set("improvement_target", targetFilter);
    if (explanationJiraFilter) params.set("jira_key", explanationJiraFilter);
    if (humanReviewFilter !== "all") params.set("human_review_required", humanReviewFilter);
    void Promise.all([
      fetch(`/api/v2/claims/triage/explanations?${params}`).then((response) => response.json()),
      fetch("/api/v2/claims/triage/explanation-facets").then((response) => response.json()),
    ]).then(([data, facets]) => {
      setExplanations(data.explanations ?? []);
      setExplanationTotal(data.total ?? 0);
      setCategories(facets.categories ?? []);
      setTargets(facets.improvement_targets ?? []);
    }).catch(() => setError("Could not load explanations"));
  }, [activeTab, categoryFilter, targetFilter, explanationJiraFilter, humanReviewFilter, explanationPage]);

  const toggleSort = (value: string) => {
    if (sort === value) setSortDir((current) => current === "asc" ? "desc" : "asc");
    else { setSort(value); setSortDir("desc"); }
  };

  if (loading) return <div className="py-12 text-center text-gray-500">Loading claim assurance data…</div>;

  return <div>
    <h1 className="mb-1 text-2xl font-bold text-gray-900 dark:text-gray-100">Claim Triage</h1>
    <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">Occurrence-specific effective verdicts and immutable improvement histories from Claim Assurance.</p>
    {error && <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}

    {summary && <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5 lg:grid-cols-10">
      {[
        ["Occurrences", summary.total_occurrences], ["Verified", summary.verified],
        ["Pending", summary.pending], ["Supported", summary.supported],
        ["Contradicted", summary.contradicted], ["Insufficient", summary.insufficient_evidence],
        ["N/A", summary.not_applicable], ["Explained", summary.explained],
        ["Human review", summary.human_review_required], ["Jira keys", summary.jira_keys_referenced],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-gray-200 bg-white p-3 text-center dark:border-gray-700 dark:bg-gray-800">
        <div className="text-xl font-bold">{value}</div><div className="mt-1 text-[10px] uppercase text-gray-500">{label}</div>
      </div>)}
    </div>}

    {types.length > 0 && <div className="mb-5 flex flex-wrap gap-2">
      {types.map((item) => <button key={item.claim_type} onClick={() => { setTypeFilter(typeFilter === item.claim_type ? "all" : item.claim_type); setPage(0); }}>
        <Badge value={`${item.claim_type} ${item.count}`} className={TYPE_CLASSES[item.claim_type]} />
      </button>)}
    </div>}

    <div className="mb-6 flex border-b border-gray-200 dark:border-gray-700">
      {(["claims", "issues", "explanations"] as const).map((tab) => <button key={tab} onClick={() => setActiveTab(tab)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${activeTab === tab ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500"}`}>{tab === "claims" ? "By occurrence" : tab === "issues" ? "By issue" : "Explanations"}</button>)}
    </div>

    {activeTab === "claims" && <>
      <div className="mb-4 flex flex-wrap gap-2">
        <input aria-label="Search claims" placeholder="Search text or occurrence ID" value={searchFilter} onChange={(event) => { setSearchFilter(event.target.value); setPage(0); }} className="min-w-64 flex-1 rounded border p-2 text-sm dark:bg-gray-900" />
        <input aria-label="Source filter" placeholder="Source file" value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); setPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900" />
        <input aria-label="Jira filter" placeholder="Jira key" value={jiraFilter} onChange={(event) => { setJiraFilter(event.target.value); setPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900" />
        <select aria-label="Verdict filter" value={verdictFilter} onChange={(event) => { setVerdictFilter(event.target.value); setPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900">
          <option value="all">All verdicts</option><option value="pending">Not verified</option>
          <option value="supported">Supported</option><option value="contradicted">Contradicted</option>
          <option value="insufficient_evidence">Insufficient evidence</option><option value="not_applicable">Not applicable</option>
        </select>
        <span className="self-center text-sm text-gray-500">{occurrenceTotal} occurrences</span>
      </div>
      {occurrences.length === 0 ? <EmptyState text={verdictFilter === "pending" ? "No unverified occurrences match these filters." : "No claim occurrences match these filters."} /> : <div className="mb-4 overflow-x-auto rounded-xl border bg-white dark:border-gray-700 dark:bg-gray-800">
        <table className="w-full text-left text-sm"><thead className="bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-900/40"><tr>
          {["claim", "type", "verdict", "confidence", "source"].map((column) => <th key={column} onClick={() => toggleSort(column)} className="cursor-pointer px-4 py-3">{column}{sort === column ? sortDir === "asc" ? " ▲" : " ▼" : ""}</th>)}
          <th>Severity</th><th>Explanation</th><th>Jira</th>
        </tr></thead><tbody className="divide-y dark:divide-gray-700">{occurrences.map((occurrence) => <tr key={occurrence.id} onClick={() => selectOccurrence(occurrence.id)} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40">
          <td className="max-w-xl px-4 py-3"><span className="mr-2 text-xs text-gray-400">#{occurrence.id}</span>{occurrence.claim_text}</td>
          <td><Badge value={occurrence.claim_type} className={TYPE_CLASSES[occurrence.claim_type]} /></td>
          <td>{occurrence.verdict ? <Badge value={occurrence.verdict} className={verdictClass(occurrence.verdict)} /> : <Badge value="not verified" />}</td>
          <td>{occurrence.confidence == null ? "—" : `${occurrence.confidence}%`}</td>
          <td className="max-w-48 truncate font-mono text-xs" title={occurrence.source_file}>{occurrence.source_file}</td>
          <td>{occurrence.severity ? <Badge value={occurrence.severity} /> : "—"}</td>
          <td><div>{occurrence.explanation_category ? <Badge value={occurrence.explanation_category} /> : <span className="text-xs text-gray-400">{processingStateLabel(occurrence.processing_state)}</span>}</div>{occurrence.improvement_target && <div className="mt-1 text-xs text-gray-500">{occurrence.improvement_target}</div>}{occurrence.human_review_required === 1 && <Badge value="human review" className="bg-amber-100 text-amber-800" />}</td>
          <td className="font-mono text-xs">{occurrence.jira_keys.join(", ") || "—"}</td>
        </tr>)}</tbody></table>
      </div>}
      {occurrenceTotal > pageSize && <Pagination page={page} pages={Math.ceil(occurrenceTotal / pageSize)} setPage={setPage} />}
    </>}

    {activeTab === "issues" && (issues.length === 0 ? <EmptyState text="No Jira-linked claim occurrences." /> : <div className="overflow-x-auto rounded-xl border bg-white dark:border-gray-700 dark:bg-gray-800"><table className="w-full text-sm"><thead><tr>{["Issue", "Occurrences", "Supported", "Contradicted", "Insufficient", "N/A", "Pending"].map((label) => <th key={label} className="px-4 py-3 text-left text-xs uppercase text-gray-500">{label}</th>)}</tr></thead><tbody>{issues.map((issue) => <tr key={issue.jira_key} onClick={() => { setJiraFilter(issue.jira_key); setActiveTab("claims"); setPage(0); }} className="cursor-pointer border-t hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-700/40"><td className="px-4 py-3 font-mono text-primary-600">{issue.jira_key}</td><td>{issue.total_occurrences}</td><td>{issue.supported}</td><td className="text-red-600">{issue.contradicted}</td><td>{issue.insufficient_evidence}</td><td>{issue.not_applicable}</td><td>{issue.pending}</td></tr>)}</tbody></table></div>)}

    {activeTab === "explanations" && <>
      <div className="mb-4 flex flex-wrap gap-2">
        <select aria-label="Explanation category" value={categoryFilter} onChange={(event) => { setCategoryFilter(event.target.value); setExplanationPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900"><option value="">All categories</option>{categories.map((item) => <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select>
        <select aria-label="Improvement target" value={targetFilter} onChange={(event) => { setTargetFilter(event.target.value); setExplanationPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900"><option value="">All targets</option>{targets.map((item) => <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select>
        <input aria-label="Explanation Jira filter" placeholder="Jira key" value={explanationJiraFilter} onChange={(event) => { setExplanationJiraFilter(event.target.value); setExplanationPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900" />
        <select aria-label="Human review filter" value={humanReviewFilter} onChange={(event) => { setHumanReviewFilter(event.target.value); setExplanationPage(0); }} className="rounded border p-2 text-sm dark:bg-gray-900"><option value="all">Any review state</option><option value="true">Human review required</option><option value="false">Routed automatically</option></select>
        <span className="self-center text-sm text-gray-500">{explanationTotal} explanation runs</span>
      </div>
      {explanations.length === 0 ? <EmptyState text="No immutable explanation runs match these filters." /> : <div className="overflow-x-auto rounded-xl border bg-white dark:border-gray-700 dark:bg-gray-800"><table className="w-full text-sm"><thead><tr>{["Category", "Target", "Claim", "Verdict", "Review", "Jira"].map((label) => <th key={label} className="px-4 py-3 text-left text-xs uppercase text-gray-500">{label}</th>)}</tr></thead><tbody>{explanations.map((explanation) => <tr key={explanation.id} onClick={() => selectOccurrence(explanation.claim_occurrence_id!)} className="cursor-pointer border-t hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-700/40"><td className="px-4 py-3"><Badge value={explanation.category} /></td><td>{explanation.improvement_target || "—"}</td><td className="max-w-xl"><span className="mr-2 text-xs text-gray-400">#{explanation.claim_occurrence_id}</span>{explanation.claim_text}</td><td><Badge value={explanation.verdict!} className={verdictClass(explanation.verdict!)} /></td><td>{explanation.human_review_required === 1 ? <Badge value="required" className="bg-amber-100 text-amber-800" /> : "—"}</td><td className="font-mono text-xs">{explanation.jira_keys?.join(", ") || "—"}</td></tr>)}</tbody></table></div>}
      {explanationTotal > 50 && <Pagination page={explanationPage} pages={Math.ceil(explanationTotal / 50)} setPage={setExplanationPage} />}
    </>}

    {(history || loadingHistory) && <HistoryModal history={history} loading={loadingHistory} close={closeHistory} />}
  </div>;
}

function HistoryModal({ history, loading, close }: { history: History | null; loading: boolean; close: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={close}><div className="flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl dark:bg-gray-800" onClick={(event) => event.stopPropagation()}>
    <div className="flex items-center justify-between border-b px-6 py-3 dark:border-gray-700"><div className="font-semibold">{history ? `Occurrence #${history.occurrence.id}` : "Loading occurrence…"}</div><button onClick={close}><X size={18} /></button></div>
    <div className="flex-1 overflow-y-auto p-6">{loading || !history ? <div className="text-gray-500">Loading immutable history…</div> : <div className="space-y-6">
      <div><div className="flex flex-wrap gap-2"><Badge value={history.occurrence.claim_type} className={TYPE_CLASSES[history.occurrence.claim_type]} /><Badge value={processingStateLabel(history.processing_state)} />{history.jira_keys.map((key) => <Badge key={key} value={key} />)}</div><p className="mt-3 text-lg">{history.occurrence.claim_text}</p><div className="mt-2 font-mono text-xs text-gray-500">{history.occurrence.source_file} · {history.occurrence.source_locator}</div>{history.occurrence.original_text && <blockquote className="mt-2 border-l-2 pl-3 text-sm text-gray-500">{history.occurrence.original_text}</blockquote>}</div>
      {history.verification_runs.length === 0 ? <EmptyState text="Not verified. No immutable verification run exists for this occurrence." /> : <div className="space-y-4"><h2 className="font-semibold">Verification and explanation history</h2>{history.verification_runs.map((verification) => <div key={verification.id} className={`rounded-lg border p-4 dark:border-gray-700 ${verification.id === history.effective_verification_run_id ? "ring-2 ring-primary-400" : ""}`}>
        <div className="flex flex-wrap items-center gap-2"><Badge value={verification.verdict} className={verdictClass(verification.verdict)} />{verification.severity && <Badge value={verification.severity} />}{verification.id === history.effective_verification_run_id && <Badge value="effective" className="bg-primary-100 text-primary-800" />}<span className="text-xs text-gray-500">run #{verification.id} · {verification.confidence}% · {verification.verifier_revision}</span></div>
        {verification.evidence_summary && <p className="mt-2 text-sm">{verification.evidence_summary}</p>}<EvidenceList evidence={verification.evidence} />
        {verification.explanation_runs.length === 0 ? <p className="mt-3 text-sm text-gray-500">Verified without explanation.</p> : verification.explanation_runs.map((explanation) => <div key={explanation.id} className="mt-4 rounded bg-gray-50 p-4 dark:bg-gray-900/40"><div className="flex flex-wrap gap-2"><Badge value={explanation.category} />{explanation.improvement_target && <Badge value={`target: ${explanation.improvement_target}`} />}{explanation.human_review_required === 1 && <Badge value="human review required" className="bg-amber-100 text-amber-800" />}{explanation.id === history.effective_explanation_run_id && <Badge value="effective" className="bg-primary-100 text-primary-800" />}</div><p className="mt-3">{explanation.explanation}</p>{explanation.contributing_factors.length > 0 && <List title="Contributing factors" values={explanation.contributing_factors} />}{explanation.alternative_explanations.length > 0 && <List title="Alternatives" values={explanation.alternative_explanations} />}{explanation.remediation && <p className="mt-3 text-sm"><strong>Remediation:</strong> {explanation.remediation}</p>}{explanation.regression_test && <p className="mt-2 text-sm"><strong>Regression test:</strong> {explanation.regression_test}</p>}<EvidenceList evidence={explanation.evidence} />{explanation.regression_runs.map((regression) => <div key={regression.id} className="mt-3 rounded border p-2 text-xs dark:border-gray-700">Regression <Badge value={regression.status} /> <span className="font-mono">{regression.dataset_fqn} · {regression.implementation_revision}</span>{regression.run_uri && <div>{regression.run_uri}</div>}</div>)}</div>)}
      </div>)}</div>}
      {history.human_overrides.length > 0 && <div><h2 className="font-semibold">Human overrides</h2>{history.human_overrides.map((override) => <div key={override.id} className="mt-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><strong>{override.decision}</strong> by {override.actor} for verification run #{override.verification_run_id}<p>{override.rationale}</p></div>)}</div>}
    </div>}</div>
  </div></div>;
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;
  return <details className="mt-3 text-xs"><summary>Structured evidence ({evidence.length})</summary><ul className="mt-2 space-y-1">{evidence.map((item) => <li key={item.id}><Badge value={item.relationship || item.evidence_type} /> <span className="font-mono">{item.uri || item.source_locator || item.query || item.authority}</span>{item.repository_revision && <span className="text-gray-500"> @ {item.repository_revision}</span>}</li>)}</ul></details>;
}

function List({ title, values }: { title: string; values: string[] }) {
  return <div className="mt-3 text-sm"><strong>{title}:</strong><ul className="ml-5 list-disc">{values.map((value) => <li key={value}>{value}</li>)}</ul></div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed p-10 text-center text-sm text-gray-500 dark:border-gray-700">{text}</div>;
}

function Pagination({ page, pages, setPage }: { page: number; pages: number; setPage: (page: number) => void }) {
  return <div className="mt-4 flex items-center justify-center gap-4"><button disabled={page === 0} onClick={() => setPage(Math.max(0, page - 1))} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Previous</button><span className="text-sm text-gray-500">Page {page + 1} of {pages}</span><button disabled={page >= pages - 1} onClick={() => setPage(Math.min(pages - 1, page + 1))} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Next</button></div>;
}

export default Hallucinations;
