// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Hallucinations from "./Hallucinations";


const occurrence = {
  id: 7,
  normalized_claim_id: 2,
  claim_text: "The component retains immutable history.",
  claim_type: "architectural",
  source_file: "artifacts/RFE-42/strategy.md",
  source_locator: "strategy.md:4",
  pipeline_slug: "end-to-end",
  jira_keys: ["RFE-42"],
  verification_run_id: 12,
  verdict: "contradicted",
  severity: "high",
  confidence: 96,
  evidence_summary: "The implementation contradicts the claim.",
  explanation_run_id: 20,
  explanation_category: "context_gap",
  improvement_target: "architecture context",
  human_review_required: 1,
  processing_state: "explanation_requires_human_review",
  override_count: 1,
};

const history = {
  occurrence: { ...occurrence, original_text: "The component retains history." },
  jira_keys: ["RFE-42"],
  effective_verification_run_id: 12,
  effective_explanation_run_id: 20,
  processing_state: "explanation_requires_human_review",
  verification_runs: [{
    id: 12,
    verdict: "contradicted",
    severity: "high",
    confidence: 96,
    evidence_summary: "The implementation contradicts the claim.",
    verifier_revision: "verify@v2",
    evidence_context_digest: "sha256:evidence",
    created_at: "2026-07-14T10:00:00Z",
    evidence: [{
      id: 1, evidence_type: "repository_file", uri: "repo://service.py",
      repository_revision: "deadbeef", relationship: "contradicts",
    }],
    explanation_runs: [{
      id: 20,
      verification_run_id: 12,
      category: "context_gap",
      improvement_target: "architecture context",
      explanation: "Generation did not receive the versioned source.",
      contributing_factors: ["Context package omitted service.py"],
      alternative_explanations: ["Retrieval may have failed"],
      remediation: "Add service.py to versioned context.",
      regression_test: "Replay and expect a supported verdict.",
      human_review_required: 1,
      evidence: [{id: 2, evidence_type: "job_log", uri: "k8s://job/generate", relationship: "supports"}],
      regression_runs: [{
        id: 30, dataset_fqn: "local:test", implementation_revision: "fixed",
        status: "passed", metrics: {accuracy: 1},
      }],
    }],
  }],
  human_overrides: [{
    id: 40, verification_run_id: 12, actor: "reviewer@example.test",
    decision: "allow_with_followup", rationale: "Non-blocking for demo",
    created_at: "2026-07-14T11:00:00Z",
  }],
};

function response(body: unknown) {
  return Promise.resolve({ok: true, json: () => Promise.resolve(body)} as Response);
}

function mockApi(empty = false) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.includes("/triage/summary")) return response({
      total_occurrences: empty ? 0 : 1, verified: empty ? 0 : 1,
      pending: 0, supported: 0, contradicted: empty ? 0 : 1,
      insufficient_evidence: 0, not_applicable: 0, explained: empty ? 0 : 1,
      human_review_required: empty ? 0 : 1, jira_keys_referenced: empty ? 0 : 1,
    });
    if (url.includes("/triage/types")) return response(empty ? [] : [{claim_type: "architectural", count: 1}]);
    if (url.includes("/triage/occurrences")) return response({occurrences: empty ? [] : [occurrence], total: empty ? 0 : 1});
    if (url.includes("/occurrences/7/history")) return response(history);
    if (url.includes("/triage/issues")) return response({issues: [], total: 0});
    if (url.includes("/triage/explanations?")) return response({explanations: [], total: 0});
    if (url.includes("/triage/explanation-facets")) return response({
      categories: [{value: "context_gap", count: 1}],
      improvement_targets: [{value: "architecture context", count: 1}],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
}

describe("Hallucinations v2 triage UX", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders effective canonical verdicts and opens full history from a deep link", async () => {
    const api = mockApi();
    render(<MemoryRouter initialEntries={["/hallucinations?occurrence=7"]}><Hallucinations /></MemoryRouter>);

    expect((await screen.findAllByText("The component retains immutable history.")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("contradicted").length).toBeGreaterThan(0);
    expect(await screen.findByText("Occurrence #7")).toBeInTheDocument();
    expect(screen.getByText("Generation did not receive the versioned source.")).toBeInTheDocument();
    expect(screen.getByText(/Add service.py to versioned context/)).toBeInTheDocument();
    expect(screen.getAllByText("Structured evidence (1)").length).toBeGreaterThan(0);
    expect(screen.getByText("Human overrides")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/api/v2/claims/occurrences/7/history");
  });

  it("sends canonical verdict and Jira filters to the occurrence endpoint", async () => {
    const api = mockApi();
    render(<MemoryRouter><Hallucinations /></MemoryRouter>);
    await screen.findByText("The component retains immutable history.");

    fireEvent.change(screen.getByLabelText("Verdict filter"), {target: {value: "insufficient_evidence"}});
    fireEvent.change(screen.getByLabelText("Jira filter"), {target: {value: "RFE-42"}});

    await waitFor(() => expect(api.mock.calls.some(([input]) => {
      const url = String(input);
      return url.includes("verdict=insufficient_evidence") && url.includes("jira_key=RFE-42");
    })).toBe(true));
  });

  it("distinguishes an empty not-verified state", async () => {
    mockApi(true);
    render(<MemoryRouter><Hallucinations /></MemoryRouter>);
    await screen.findByText("No claim occurrences match these filters.");
    fireEvent.change(screen.getByLabelText("Verdict filter"), {target: {value: "pending"}});
    expect(await screen.findByText("No unverified occurrences match these filters.")).toBeInTheDocument();
  });

  it("filters immutable explanations by route, Jira, and review state", async () => {
    const api = mockApi();
    render(<MemoryRouter><Hallucinations /></MemoryRouter>);
    await screen.findByText("The component retains immutable history.");
    fireEvent.click(screen.getByRole("button", {name: "Explanations"}));

    await screen.findByRole("option", {name: "context_gap (1)"});
    fireEvent.change(screen.getByLabelText("Explanation category"), {target: {value: "context_gap"}});
    fireEvent.change(screen.getByLabelText("Improvement target"), {target: {value: "architecture context"}});
    fireEvent.change(screen.getByLabelText("Explanation Jira filter"), {target: {value: "RFE-42"}});
    fireEvent.change(screen.getByLabelText("Human review filter"), {target: {value: "true"}});

    await waitFor(() => expect(api.mock.calls.some(([input]) => {
      const url = String(input);
      return url.includes("/triage/explanations?")
        && url.includes("category=context_gap")
        && url.includes("improvement_target=architecture+context")
        && url.includes("jira_key=RFE-42")
        && url.includes("human_review_required=true");
    })).toBe(true));
  });
});
