// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClaimAssurance from "./ClaimAssurance";


function response(body: unknown) {
  return Promise.resolve({ok: true, json: () => Promise.resolve(body)} as Response);
}

describe("Claim Assurance effective verdict summary", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("uses the shared triage summary instead of historical run totals", async () => {
    const api = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v2/claims/summary")) return response({
        extraction_runs: 1, source_units: 297, occurrences: 297,
        unresolved_units: 0, entailed_occurrences: 297, non_entailed_occurrences: 0,
        source_entailment_rate: 1,
        verdicts: {supported: 740, contradicted: 21, insufficient_evidence: 46},
        improvement_routes: {context_gap: 38},
        receipts: {events: 0, agent_jobs_avoided: 0},
        coverage: {verifiable_element_f1: null, element_macro_f1: null},
        breakdowns: {extraction: []},
      });
      if (url.endsWith("/api/v2/claims/triage/summary")) return response({
        total_occurrences: 297, pending: 52, supported: 230,
        contradicted: 12, insufficient_evidence: 3, not_applicable: 0,
      });
      if (url.endsWith("/api/v2/claims/extraction-runs")) return response({runs: []});
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ClaimAssurance />);

    const heading = await screen.findByText("Effective verification verdicts");
    expect(heading.parentElement).toHaveTextContent("supported230");
    expect(heading.parentElement).toHaveTextContent("pending52");
    expect(heading.parentElement).not.toHaveTextContent("740");
    expect(api).toHaveBeenCalledWith("/api/v2/claims/triage/summary");
  });
});
