# Hallucination Detection Findings

Captured 2026-06-04 from initial verification run on security claims.

## First Confirmed Hallucinations (via arch-query)

These claims were refuted by cross-referencing against the architecture-context repository using `arch-query`. The agents made specific architectural assertions that contradict the documented architecture.

### 1. training-operator webhook count (Claim 254)

**Claim:** "Removal of training-operator reduces the platform's attack surface by eliminating 6 validating webhooks."

**Verdict:** REFUTED (confidence 85%)

**Evidence:** The architecture docs show training-operator has 5 validating webhooks (PyTorchJob, TFJob, XGBoostJob, JAXJob, PaddleJob). MPIJob is explicitly excluded from webhook validation. The agent counted 6 — an off-by-one hallucination.

**Source:** `arch-query component training-operator`

### 2. model-registry Istio mTLS (Claims 21349, 22021)

**Claim:** "The model-registry uses Istio mTLS" / "model-registry uses Istio mTLS for its security model"

**Verdict:** REFUTED (confidence 82%)

**Evidence:** Istio is listed as an **optional** dependency for mTLS and authorization. The internal services use plain HTTP, not mTLS. The agent presented an optional feature as a definitive architectural characteristic.

**Source:** `arch-query component model-registry` → shows `Istio (optional) - Optional service mesh for mTLS and authorization`

## Statistics (first run)

- 1,246 security claims verified
- 76 supported (91% avg confidence)
- 34 refuted (79% avg confidence)
- 10 inconclusive (38% avg confidence)
- 1,126 insufficient evidence (source material doesn't cover the claim)

## Observations

- **Off-by-one errors** in counts (webhook count) are a common hallucination pattern — the agent approximates rather than counting precisely
- **Optional features stated as facts** is another pattern — the agent doesn't distinguish between "supports X" and "uses X"
- **High insufficient rate** (90%) suggests most security claims go beyond what the source text and architecture docs cover — they may reference runtime behavior, operational procedures, or external systems not in the architecture context
- **arch-query improved verification** — 47 claims had architecture context available, catching 4 hallucinations that co-located source files alone would have missed
