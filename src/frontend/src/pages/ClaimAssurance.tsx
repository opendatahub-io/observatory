import { useEffect, useState } from "react";

interface Summary {
  extraction_runs: number;
  source_units: number;
  occurrences: number;
  unresolved_units: number;
  entailed_occurrences: number;
  non_entailed_occurrences: number;
  source_entailment_rate: number;
  verdicts: Record<string, number>;
  improvement_routes: Record<string, number>;
  receipts: { events: number; agent_jobs_avoided: number };
  coverage: { verifiable_element_f1: number | null; element_macro_f1: number | null };
  breakdowns: {
    extraction: Array<{
      artifact_type: string; extractor_revision: string; model: string;
      configuration_digest: string; extraction_runs: number;
      source_entailment_rate: number | null;
      desirable_decontextualization_rate: number | null;
      coverage: { element_macro_f1: number | null };
    }>;
  };
}

interface ExtractionRun {
  id: number;
  run_key: string;
  source_file: string;
  extractor_revision: string;
  model: string | null;
  status: string;
  source_unit_count: number;
  occurrence_count: number;
  unresolved_count: number;
  entailment_failure_count: number;
}

interface RunDetail {
  source_units: Array<{
    id: number; source_locator: string; original_text: string;
    preceding_context: string; following_context: string;
    classification: string; selected_text: string | null;
    ambiguity_status: string | null; ambiguity_rationale: string | null;
    occurrences: Array<{
      id: number; claim_text: string; original_text: string | null;
      accepted: number;
      modality: string | null; product_version: string | null;
      entailed: number | null; coverage_result: string | null;
      decontextualization_result: string | null;
      maximally_contextualized_claim: string | null;
      extracted_retrieval_digest: string | null;
      comparison_retrieval_digest: string | null;
      coverage_elements: Array<{ id: number; element_text: string; element_kind: string; coverage: string }>;
      extraction_evidence: Array<{ id: number; evidence_type: string; uri?: string; relationship?: string }>;
    }>;
  }>;
}

interface OccurrenceHistory {
  verification_runs: Array<Record<string, unknown> & {
    id: number; verdict: string; severity?: string; confidence?: number;
    evidence_summary?: string; verifier_revision: string;
    evidence: Array<{ id: number; evidence_type: string; uri?: string; source_locator?: string; relationship?: string; authority?: string }>;
    explanation_runs: Array<Record<string, unknown> & {
      id: number; category: string; improvement_target?: string;
      explanation: string; remediation?: string;
      human_review_required: number;
      regression_runs: Array<{ id: number; status: string; dataset_fqn: string }>;
    }>;
  }>;
  human_overrides: Array<{
    id: number; verification_run_id: number; actor: string;
    decision: string; rationale: string;
  }>;
}

export default function ClaimAssurance() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [history, setHistory] = useState<OccurrenceHistory | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/v2/claims/summary"),
      fetch("/api/v2/claims/extraction-runs"),
    ])
      .then(async ([summaryResponse, runsResponse]) => {
        if (!summaryResponse.ok || !runsResponse.ok) throw new Error("Claim assurance API unavailable");
        setSummary(await summaryResponse.json());
        setRuns((await runsResponse.json()).runs);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const cards = summary ? [
    ["Source units", summary.source_units],
    ["Claim occurrences", summary.occurrences],
    ["Entailment rate", `${(summary.source_entailment_rate * 100).toFixed(1)}%`],
    ["Needs review", summary.unresolved_units + summary.non_entailed_occurrences],
    ["Jobs avoided", summary.receipts.agent_jobs_avoided],
    ["Coverage macro F1", summary.coverage.element_macro_f1 == null ? "Pending" : `${(summary.coverage.element_macro_f1 * 100).toFixed(1)}%`],
  ] : [];

  const openRun = async (runId: number) => {
    const response = await fetch(`/api/v2/claims/extraction-runs/${runId}`);
    if (response.ok) setDetail(await response.json());
  };
  const openHistory = async (occurrenceId: number) => {
    const response = await fetch(`/api/v2/claims/occurrences/${occurrenceId}/history`);
    if (response.ok) setHistory(await response.json());
  };

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Claim Assurance</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Trace extraction decisions, factual verification, and improvements without collapsing their histories.
        </p>
      </div>
      {error && <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-6">
        {cards.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
            <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
            <div className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">{value}</div>
          </div>
        ))}
      </div>
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="border-b border-gray-200 px-5 py-4 font-semibold dark:border-gray-700">Extraction runs</div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-900/40">
              <tr><th className="px-5 py-3">Source</th><th>Implementation</th><th>Units</th><th>Claims</th><th>Review</th><th>Status</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {runs.map((run) => (
                <tr key={run.id} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40" onClick={() => void openRun(run.id)}>
                  <td className="max-w-sm truncate px-5 py-3" title={run.source_file}>{run.source_file}</td>
                  <td title={run.run_key}>{run.extractor_revision}{run.model ? ` · ${run.model}` : ""}</td>
                  <td>{run.source_unit_count}</td><td>{run.occurrence_count}</td>
                  <td className={run.unresolved_count + run.entailment_failure_count ? "text-amber-600" : "text-emerald-600"}>
                    {run.unresolved_count + run.entailment_failure_count}
                  </td>
                  <td>{run.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {summary && summary.breakdowns.extraction.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <div className="border-b border-gray-200 px-5 py-4 dark:border-gray-700">
            <div className="font-semibold">Extraction comparisons</div>
            <div className="mt-1 text-xs text-gray-500">Grouped by artifact class, extractor, model, and configuration digest.</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-900/40">
                <tr><th className="px-5 py-3">Artifact</th><th>Implementation</th><th>Runs</th><th>Entailment</th><th>Macro F1</th><th>Decontextualization</th></tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {summary.breakdowns.extraction.map((item) => (
                  <tr key={`${item.artifact_type}:${item.extractor_revision}:${item.model}:${item.configuration_digest}`}>
                    <td className="px-5 py-3">{item.artifact_type}</td>
                    <td><div>{item.extractor_revision}{item.model ? ` · ${item.model}` : ""}</div><div className="max-w-xs truncate font-mono text-xs text-gray-500" title={item.configuration_digest}>{item.configuration_digest || "unrecorded config"}</div></td>
                    <td>{item.extraction_runs}</td>
                    <td>{formatRate(item.source_entailment_rate)}</td>
                    <td>{formatRate(item.coverage.element_macro_f1)}</td>
                    <td>{formatRate(item.desirable_decontextualization_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {detail && <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center justify-between"><h2 className="font-semibold">Source decision trace</h2><button className="text-sm text-gray-500" onClick={() => setDetail(null)}>Close</button></div>
        <div className="mt-4 space-y-4">{detail.source_units.map((unit) => <div key={unit.id} className="rounded-lg border border-gray-200 p-4 dark:border-gray-700">
          <div className="flex flex-wrap gap-2 text-xs"><span className="font-mono">{unit.source_locator}</span><Badge value={unit.classification} /><Badge value={unit.ambiguity_status ?? "not evaluated"} /></div>
          <p className="mt-3 whitespace-pre-wrap text-sm">{unit.original_text}</p>
          {(unit.preceding_context !== "[]" || unit.following_context !== "[]") && <details className="mt-2 text-xs text-gray-500"><summary>Context window</summary><pre className="mt-1 whitespace-pre-wrap">{unit.preceding_context}{"\n"}{unit.following_context}</pre></details>}
          {unit.occurrences.map((occurrence) => <button type="button" onClick={() => void openHistory(occurrence.id)} key={occurrence.id} className="mt-3 block w-full border-l-2 border-primary-500 pl-3 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700/40">
            <div>{occurrence.claim_text}</div>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500"><Badge value={occurrence.accepted === 1 ? "accepted" : "rejected candidate"} /><Badge value={occurrence.entailed === 1 ? "entailed" : "entailment failed"} /><Badge value={occurrence.coverage_result ?? "coverage pending"} /><Badge value={occurrence.decontextualization_result ?? "context review pending"} />{occurrence.modality && <span>modality: {occurrence.modality}</span>}{occurrence.product_version && <span>version: {occurrence.product_version}</span>}</div>
            {occurrence.coverage_elements.length > 0 && <div className="mt-2 space-y-1 text-xs">{occurrence.coverage_elements.map((element) => <div key={element.id}><Badge value={`${element.element_kind}: ${element.coverage}`} /> {element.element_text}</div>)}</div>}
            {occurrence.extraction_evidence.length > 0 && <div className="mt-2 text-xs text-gray-500">Extraction evidence: {occurrence.extraction_evidence.map((evidence) => evidence.uri ?? evidence.evidence_type).join(", ")}</div>}
            {occurrence.maximally_contextualized_claim && <details className="mt-2 text-xs text-gray-500"><summary>Decontextualization comparison</summary><p className="mt-1">{occurrence.maximally_contextualized_claim}</p><p className="font-mono">{occurrence.extracted_retrieval_digest} ↔ {occurrence.comparison_retrieval_digest}</p></details>}
          </button>)}
        </div>)}</div>
      </div>}
      {history && <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex justify-between"><h2 className="font-semibold">Verification and improvement history</h2><button className="text-sm text-gray-500" onClick={() => setHistory(null)}>Close</button></div>
        <div className="mt-4 space-y-4">{history.verification_runs.map((run) => <div key={run.id} className="rounded-lg border border-gray-200 p-4 dark:border-gray-700">
          <div className="flex flex-wrap gap-2"><Badge value={run.verdict} />{run.severity && <Badge value={run.severity} />}<span className="text-xs text-gray-500">{run.verifier_revision}{run.confidence != null ? ` · triage ${run.confidence}` : ""}</span></div>
          {run.evidence_summary && <p className="mt-2 text-sm">{run.evidence_summary}</p>}
          {run.evidence.length > 0 && <details className="mt-2 text-xs"><summary>Evidence ({run.evidence.length})</summary><ul className="mt-1 space-y-1">{run.evidence.map((evidence) => <li key={evidence.id}><Badge value={evidence.relationship ?? evidence.evidence_type} /> {evidence.uri ?? evidence.source_locator ?? evidence.authority}</li>)}</ul></details>}
          {run.explanation_runs.map((explanation) => <div key={explanation.id} className="mt-3 rounded bg-gray-50 p-3 text-sm dark:bg-gray-900/40">
            <div className="flex gap-2"><Badge value={explanation.category} />{explanation.human_review_required === 1 && <Badge value="human review required" />}{explanation.improvement_target && <span>Target: {explanation.improvement_target}</span>}</div>
            <p className="mt-2">{explanation.explanation}</p>{explanation.remediation && <p className="mt-1 text-gray-500">Remediation: {explanation.remediation}</p>}
            {explanation.regression_runs.map((regression) => <div key={regression.id} className="mt-2 text-xs">Regression <Badge value={regression.status} /> <span className="font-mono">{regression.dataset_fqn}</span></div>)}
          </div>)}
        </div>)}</div>
        {history.human_overrides.map((override) => <div key={override.id} className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><strong>Human override: {override.decision}</strong> by {override.actor} for verification run #{override.verification_run_id}<p>{override.rationale}</p></div>)}
      </div>}
      {summary && (
        <div className="grid gap-4 md:grid-cols-2">
          <MetricList title="Verification verdicts" values={summary.verdicts} />
          <MetricList title="Improvement routes" values={summary.improvement_routes} />
        </div>
      )}
    </div>
  );
}

function formatRate(value: number | null) {
  return value == null ? "Pending" : `${(value * 100).toFixed(1)}%`;
}

function Badge({ value }: { value: string }) {
  return <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-700 dark:bg-gray-700 dark:text-gray-200">{value}</span>;
}

function MetricList({ title, values }: { title: string; values: Record<string, number> }) {
  return <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
    <h2 className="font-semibold">{title}</h2>
    <dl className="mt-3 space-y-2 text-sm">{Object.entries(values).map(([key, value]) =>
      <div key={key} className="flex justify-between"><dt>{key.replace(/_/g, " ")}</dt><dd className="font-mono">{value}</dd></div>
    )}</dl>
  </div>;
}
