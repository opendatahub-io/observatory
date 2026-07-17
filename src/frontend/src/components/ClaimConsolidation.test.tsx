// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClaimConsolidation from "./ClaimConsolidation";


function response(body: unknown, ok = true) {
  return Promise.resolve({ok, json: () => Promise.resolve(body)} as Response);
}


describe("ClaimConsolidation", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("reviews candidates and exposes group provenance and split controls", async () => {
    const requests: Array<{url: string; method: string; body?: string}> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      requests.push({url, method: init?.method ?? "GET", body: init?.body as string});
      if (url.endsWith("/summary")) return response({
        occurrence_count: 11, text_identity_count: 10, canonical_group_count: 1,
        multi_member_group_count: 1, unreviewed_candidate_count: 1,
      });
      if (url.includes("/candidates?")) return response({candidates: [{
        id: 5, left_normalized_claim_id: 12, right_normalized_claim_id: 19,
        left_claim_text: "rhai-cli is absent from the inventory.",
        right_claim_text: "The inventory does not include rhai-cli.",
        retrieval_score: 0.91, decision: "needs_review",
        compared_qualifiers: {product_version: "3.5-ea.2"},
      }]});
      if (url.endsWith("/groups?limit=100")) return response({groups: [{
        id: 3, canonical_text: "RHOAI inventory excludes rhai-cli",
        member_count: 2, occurrence_count: 4, policy_revision: "human-v1",
      }]});
      if (url.endsWith("/evaluations?limit=5")) return response({evaluations: [{
        evaluation_run_id: "semantic-claim-equivalence-v1-baseline",
        labeled_dataset_revision: "semantic-claim-equivalence-v1",
        precision: null,
        recall: 0,
        false_merge_rate: null,
        equivalent_prediction_count: 0,
        false_negative_count: 5,
      }]});
      if (url.endsWith("/verification-reuse-opportunities")) return response({
        reuse_enabled: false,
        reuse_policy: {status: "simulation_only", required_compatibility: []},
        compatible_run_count: 2,
        simulation: {
          simulated_reused_run_count: 1,
          simulated_agreeing_reuse_count: 1,
          simulated_disagreeing_reuse_count: 0,
          agreement_rate: 1,
          estimated_saved_tokens: 100,
          estimated_saved_cost_usd: 0.5,
        },
        invalidation: {
          groups_with_invalidation_count: 1,
          reason_group_counts: {verifier_revision: 1},
        },
      });
      if (url.endsWith("/groups/3")) return response({
        id: 3, canonical_text: "RHOAI inventory excludes rhai-cli",
        member_count: 2, occurrence_count: 4, policy_revision: "human-v1",
        members: [{
          normalized_claim_id: 12, claim_text: "rhai-cli is absent.",
          occurrence_count: 1,
          occurrences: [{id: 7, source_file: "strategy.md", source_locator: "strategy.md:4"}],
        }],
        decisions: [{id: 8, decision: "equivalent", rationale: "Mutual entailment", decider_type: "human"}],
        related_claims: [],
      });
      if (url.includes("/decisions") || url.includes("/split")) return response({});
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ClaimConsolidation />);
    expect(await screen.findByText("11")).toBeInTheDocument();
    expect(screen.getByText("semantic-claim-equivalence-v1-baseline")).toBeInTheDocument();
    expect(screen.getByText("Automatic grouping is not authorized by this run.")).toBeInTheDocument();
    expect(screen.getByText(/Status: simulation only/)).toBeInTheDocument();
    expect(screen.getByText("Saved tokens: 100")).toBeInTheDocument();
    expect(screen.getByText("rhai-cli is absent from the inventory.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Consolidation reviewer"), {
      target: {value: "reviewer@example.test"},
    });
    fireEvent.change(screen.getByLabelText("Rationale for candidate 5"), {
      target: {value: "Same assertion and qualifiers"},
    });
    fireEvent.click(screen.getByRole("button", {name: "equivalent"}));
    await waitFor(() => expect(requests.some((request) =>
      request.url.endsWith("/candidates/5/decisions") && request.method === "POST"
    )).toBe(true));

    fireEvent.click(screen.getByText(/Group #3/));
    expect(await screen.findByText(/Occurrence #7/)).toBeInTheDocument();
    expect(screen.getByText(/human equivalent: Mutual entailment/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "Split"}));
    await waitFor(() => expect(requests.some((request) =>
      request.url.endsWith("/groups/3/split") && request.method === "POST"
    )).toBe(true));
  });
});
