import { useCallback, useEffect, useState } from "react";


interface ConsolidationSummary {
  occurrence_count: number;
  text_identity_count: number;
  canonical_group_count: number;
  multi_member_group_count: number;
  unreviewed_candidate_count: number;
}

interface Candidate {
  id: number;
  left_normalized_claim_id: number;
  right_normalized_claim_id: number;
  left_claim_text: string;
  right_claim_text: string;
  retrieval_score: number;
  decision?: string;
  rationale?: string;
  compared_qualifiers?: Record<string, unknown>;
}

interface GroupSummary {
  id: number;
  canonical_text: string;
  member_count: number;
  occurrence_count: number;
  policy_revision: string;
}

interface GroupMember {
  normalized_claim_id: number;
  claim_text: string;
  occurrence_count: number;
  occurrences: Array<{id: number; source_file: string; source_locator: string}>;
}

interface GroupDetail extends GroupSummary {
  members: GroupMember[];
  decisions: Array<{id: number; decision: string; rationale: string; decider_type: string}>;
  related_claims: Array<{candidate_id: number; rationale: string}>;
}

interface EvaluationRecord {
  evaluation_run_id: string;
  labeled_dataset_revision: string;
  precision: number | null;
  recall: number | null;
  false_merge_rate: number | null;
  equivalent_prediction_count: number;
  false_negative_count: number;
}

interface ReuseReport {
  reuse_enabled: boolean;
  reuse_policy: {status: string; required_compatibility: string[]};
  compatible_run_count: number;
  simulation: {
    simulated_reused_run_count: number;
    simulated_agreeing_reuse_count: number;
    simulated_disagreeing_reuse_count: number;
    agreement_rate: number | null;
    estimated_saved_tokens: number;
    estimated_saved_cost_usd: number;
  };
  invalidation: {
    groups_with_invalidation_count: number;
    reason_group_counts: Record<string, number>;
  };
}


function formatPercent(value: number | null) {
  return value === null ? "not measured" : `${(value * 100).toFixed(1)}%`;
}


function ClaimConsolidation() {
  const [summary, setSummary] = useState<ConsolidationSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [evaluations, setEvaluations] = useState<EvaluationRecord[]>([]);
  const [reuseReport, setReuseReport] = useState<ReuseReport | null>(null);
  const [details, setDetails] = useState<Record<number, GroupDetail>>({});
  const [rationales, setRationales] = useState<Record<number, string>>({});
  const [actor, setActor] = useState("");
  const [canonicalText, setCanonicalText] = useState("");
  const [claimIds, setClaimIds] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [
      summaryResponse,
      candidateResponse,
      groupResponse,
      evaluationResponse,
      reuseResponse,
    ] = await Promise.all([
      fetch("/api/v2/claim-consolidation/summary"),
      fetch("/api/v2/claim-consolidation/candidates?decision=needs_review&limit=100"),
      fetch("/api/v2/claim-consolidation/groups?limit=100"),
      fetch("/api/v2/claim-consolidation/evaluations?limit=5"),
      fetch("/api/v2/claim-consolidation/verification-reuse-opportunities"),
    ]);
    if (
      !summaryResponse.ok || !candidateResponse.ok || !groupResponse.ok
      || !evaluationResponse.ok || !reuseResponse.ok
    ) {
      throw new Error("Claim consolidation review API unavailable");
    }
    setSummary(await summaryResponse.json());
    setCandidates((await candidateResponse.json()).candidates ?? []);
    setGroups((await groupResponse.json()).groups ?? []);
    setEvaluations((await evaluationResponse.json()).evaluations ?? []);
    setReuseReport(await reuseResponse.json());
  }, []);

  useEffect(() => {
    void load().catch((reason: Error) => setError(reason.message));
  }, [load]);

  const decide = async (candidate: Candidate, decision: string) => {
    const rationale = rationales[candidate.id]?.trim();
    if (!actor.trim() || !rationale) {
      setError("Reviewer and rationale are required for every decision.");
      return;
    }
    const response = await fetch(
      `/api/v2/claim-consolidation/candidates/${candidate.id}/decisions`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          decision, rationale, actor, confidence: 1,
          decider_revision: "claim-consolidation-ui@v1",
          compared_qualifiers: candidate.compared_qualifiers ?? {},
        }),
      },
    );
    if (!response.ok) {
      setError((await response.json()).detail ?? "Could not record decision");
      return;
    }
    setError(null);
    await load();
  };

  const openGroup = async (groupId: number) => {
    if (details[groupId]) {
      setDetails((current) => {
        const next = {...current};
        delete next[groupId];
        return next;
      });
      return;
    }
    const response = await fetch(`/api/v2/claim-consolidation/groups/${groupId}`);
    if (!response.ok) return setError("Could not load canonical group");
    const detail = await response.json();
    setDetails((current) => ({...current, [groupId]: detail}));
  };

  const split = async (groupId: number, claimId: number) => {
    const response = await fetch(`/api/v2/claim-consolidation/groups/${groupId}/split`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        normalized_claim_ids: [claimId], actor,
        policy_revision: "claim-consolidation-ui@v1",
      }),
    });
    if (!response.ok) return setError((await response.json()).detail ?? "Could not split group");
    setDetails((current) => {
      const next = {...current};
      delete next[groupId];
      return next;
    });
    await load();
  };

  const retire = async (groupId: number) => {
    const response = await fetch(`/api/v2/claim-consolidation/groups/${groupId}/retire`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({actor, rationale: "Retired through claim consolidation review UI"}),
    });
    if (!response.ok) return setError((await response.json()).detail ?? "Could not retire group");
    await load();
  };

  const create = async () => {
    const normalizedClaimIds = claimIds.split(",").map(Number).filter(Number.isInteger);
    const response = await fetch("/api/v2/claim-consolidation/groups", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        canonical_text: canonicalText, normalized_claim_ids: normalizedClaimIds,
        policy_revision: "claim-consolidation-ui@v1", actor,
      }),
    });
    if (!response.ok) return setError((await response.json()).detail ?? "Could not create group");
    setCanonicalText("");
    setClaimIds("");
    await load();
  };

  return <div className="space-y-6">
    {error && <div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    {summary && <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {[
        ["Occurrences", summary.occurrence_count],
        ["Text identities", summary.text_identity_count],
        ["Canonical groups", summary.canonical_group_count],
        ["Multi-member", summary.multi_member_group_count],
        ["Unreviewed", summary.unreviewed_candidate_count],
      ].map(([label, value]) => <div key={label} className="rounded-xl border p-3 text-center dark:border-gray-700"><div className="text-xl font-bold">{value}</div><div className="text-xs text-gray-500">{label}</div></div>)}
    </div>}

    <label className="block text-sm">Reviewer
      <input aria-label="Consolidation reviewer" value={actor} onChange={(event) => setActor(event.target.value)} placeholder="reviewer@example.com" className="ml-3 rounded border p-2 dark:bg-gray-900" />
    </label>

    <section className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-xl border p-4 dark:border-gray-700">
        <h2 className="mb-3 font-semibold">Automatic assignment gate</h2>
        {evaluations.length === 0 ? <p className="text-sm text-gray-500">No evaluation runs recorded.</p> : <div className="space-y-2 text-sm">
          {evaluations.map((evaluation) => <div key={evaluation.evaluation_run_id} className="rounded bg-gray-50 p-3 dark:bg-gray-900/40">
            <div className="font-medium">{evaluation.evaluation_run_id}</div>
            <div className="text-xs text-gray-500">Dataset {evaluation.labeled_dataset_revision}</div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <span>Precision: {formatPercent(evaluation.precision)}</span>
              <span>Recall: {formatPercent(evaluation.recall)}</span>
              <span>False merge: {formatPercent(evaluation.false_merge_rate)}</span>
              <span>Predictions: {evaluation.equivalent_prediction_count}</span>
            </div>
            {evaluation.precision === null && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">Automatic grouping is not authorized by this run.</p>}
          </div>)}
        </div>}
      </div>
      <div className="rounded-xl border p-4 dark:border-gray-700">
        <h2 className="mb-3 font-semibold">Verification reuse simulation</h2>
        {!reuseReport ? <p className="text-sm text-gray-500">Reuse simulation unavailable.</p> : <div className="space-y-2 text-sm">
          <p className="text-xs text-gray-500">Status: {reuseReport.reuse_policy.status.replace("_", " ")} · reuse enabled: {reuseReport.reuse_enabled ? "yes" : "no"}</p>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <span>Compatible runs: {reuseReport.compatible_run_count}</span>
            <span>Simulated reuse: {reuseReport.simulation.simulated_reused_run_count}</span>
            <span>Agreement: {formatPercent(reuseReport.simulation.agreement_rate)}</span>
            <span>Saved tokens: {reuseReport.simulation.estimated_saved_tokens}</span>
          </div>
          <p className="text-xs text-gray-500">Invalidated groups: {reuseReport.invalidation.groups_with_invalidation_count}</p>
        </div>}
      </div>
    </section>

    <section><h2 className="mb-3 font-semibold">Equivalence review queue</h2>
      {candidates.length === 0 ? <p className="text-sm text-gray-500">No candidates currently need review.</p> : <div className="space-y-3">{candidates.map((candidate) => <div key={candidate.id} className="rounded-xl border p-4 dark:border-gray-700">
        <div className="grid gap-3 md:grid-cols-2"><div><span className="text-xs text-gray-400">Text identity #{candidate.left_normalized_claim_id}</span><p>{candidate.left_claim_text}</p></div><div><span className="text-xs text-gray-400">Text identity #{candidate.right_normalized_claim_id}</span><p>{candidate.right_claim_text}</p></div></div>
        <p className="mt-2 text-xs text-gray-500">Retrieval score {candidate.retrieval_score.toFixed(3)} · latest decision {candidate.decision}</p>
        <div className="mt-3 flex flex-wrap gap-2"><input aria-label={`Rationale for candidate ${candidate.id}`} value={rationales[candidate.id] ?? ""} onChange={(event) => setRationales((current) => ({...current, [candidate.id]: event.target.value}))} placeholder="Qualifier-aware rationale" className="min-w-64 flex-1 rounded border p-2 text-sm dark:bg-gray-900" />
          {(["equivalent", "related", "distinct", "needs_review"] as const).map((decision) => <button key={decision} onClick={() => void decide(candidate, decision)} className="rounded border px-3 py-2 text-xs capitalize hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-700">{decision.replace("_", " ")}</button>)}
        </div>
      </div>)}</div>}
    </section>

    <section><h2 className="mb-3 font-semibold">Create reviewed group</h2><div className="flex flex-wrap gap-2">
      <input aria-label="Canonical text" value={canonicalText} onChange={(event) => setCanonicalText(event.target.value)} placeholder="Readable canonical label" className="min-w-64 flex-1 rounded border p-2 text-sm dark:bg-gray-900" />
      <input aria-label="Text identity IDs" value={claimIds} onChange={(event) => setClaimIds(event.target.value)} placeholder="Text identity IDs: 12, 19" className="rounded border p-2 text-sm dark:bg-gray-900" />
      <button onClick={() => void create()} className="rounded bg-primary-600 px-4 py-2 text-sm text-white">Create group</button>
    </div></section>

    <section><h2 className="mb-3 font-semibold">Canonical groups</h2>
      {groups.length === 0 ? <p className="text-sm text-gray-500">No reviewed canonical groups.</p> : <div className="space-y-2">{groups.map((group) => {
        const detail = details[group.id];
        return <div key={group.id} className="rounded-xl border dark:border-gray-700">
          <button onClick={() => void openGroup(group.id)} className="flex w-full items-center justify-between p-4 text-left"><span><strong>Group #{group.id}</strong> · {group.canonical_text}</span><span className="text-xs text-gray-500">{group.member_count} texts · {group.occurrence_count} occurrences</span></button>
          {detail && <div className="border-t p-4 dark:border-gray-700"><div className="space-y-3">{detail.members.filter((member) => member.occurrence_count > 0).map((member) => <div key={member.normalized_claim_id} className="rounded bg-gray-50 p-3 dark:bg-gray-900/40"><div className="flex justify-between gap-3"><span><strong>#{member.normalized_claim_id}</strong> {member.claim_text}</span><button disabled={!actor} onClick={() => void split(group.id, member.normalized_claim_id)} className="text-xs text-red-600 disabled:opacity-40">Split</button></div><ul className="mt-2 text-xs text-gray-500">{member.occurrences.map((occurrence) => <li key={occurrence.id}>Occurrence #{occurrence.id} · {occurrence.source_file}:{occurrence.source_locator}</li>)}</ul></div>)}</div>
            {detail.decisions.map((decision) => <p key={decision.id} className="mt-2 text-xs text-gray-500">{decision.decider_type} {decision.decision}: {decision.rationale}</p>)}
            {detail.related_claims.length > 0 && <p className="mt-2 text-xs text-gray-500">{detail.related_claims.length} related-but-distinct claim links</p>}
            <button disabled={!actor} onClick={() => void retire(group.id)} className="mt-3 text-xs text-red-600 disabled:opacity-40">Retire group</button>
          </div>}
        </div>;
      })}</div>}
    </section>
  </div>;
}


export default ClaimConsolidation;
