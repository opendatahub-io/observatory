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

### 3. Security reviewer mischaracterizes cloud_id storage (Claim 4777)

**Claim:** "New credential types introduced include Elasticsearch basic auth, API key, and cloud_id stored as Kubernetes Secrets."

**Verdict:** REFUTED (confidence 90%)

**Evidence:** The source STRAT text (RHAISTRAT-1676) says basic auth (username/password) and API key are "stored as Kubernetes Secret references", but `cloud_id` is described separately as "optional cloud_id for Elastic Cloud deployments" — not as a Secret-stored credential. The security reviewer lumped all three together as "stored as Kubernetes Secrets", which misrepresents the proposal.

**Root cause:** Reviewer hallucination — the security review agent incorrectly characterized `cloud_id` as a Kubernetes Secret when the STRAT only describes it as an optional connection parameter. The claim extractor faithfully captured what the reviewer wrote. The agentic verifier caught the discrepancy by comparing the claim against the actual STRAT text.

**Significance:** This is the first finding where the hallucination originated in the *reviewer* (not the extractor or the original STRAT author). The verification pipeline correctly traced the error to its source: the reviewer's threat surface analysis inaccurately broadened the scope of Secret-stored credentials.

**Source:** `RHAISTRAT-1676-security-review.md` (threat surface analysis section) vs `RHAISTRAT-1676-strat-text.md` (connection configuration section)

### 4. NFR checklist itself is a hallucination source (Claim 4805)

**Claim:** "RHOAI has a policy of using Secret volume mounts rather than environment variable injection for credentials."

**Verdict:** REFUTED (confidence 90%)

**Evidence:** The NFR checklist says "Secrets stored in OpenShift Secrets or external secret stores, not in ConfigMaps or environment variables." But this is imprecise — it conflates two things:

1. Don't store secret *values* as plaintext environment variable definitions (correct)
2. Don't inject Secrets as environment variables at all (incorrect)

Multiple RHOAI components use `secretKeyRef` / `envFrom` to inject Kubernetes Secrets as environment variables. This is a standard, secure Kubernetes pattern — the Secret is stored in etcd, just mounted as an env var rather than a volume. The platform does not have a blanket policy favoring volume mounts.

**Root cause:** The NFR checklist — which we treat as ground truth for security reviews — contains an imprecise requirement that the security reviewer interpreted literally. The reviewer read "not in environment variables" and stated it as a platform policy of "Secret volume mounts rather than environment variable injection." The hallucination chain: imprecise checklist → reviewer over-interpretation → incorrect claim.

**Significance:** This is the first finding where the *ground truth document itself* is a source of hallucinations. The NFR checklist is authored by humans and fed to the security review agents as authoritative reference. When it's imprecise, the reviewers amplify the imprecision into concrete (incorrect) claims. Fixing the checklist would prevent an entire class of downstream hallucinations.

### 5. Reviewer promotes open question to definitive scope (Claim 4782)

**Claim:** "The STRAT targets Elasticsearch 8.x as the minimum supported version."

**Verdict:** REFUTED (confidence 90%)

**Evidence:** The STRAT (RHAISTRAT-1676) lists "What is the minimum supported Elasticsearch version?" as an **open question**, noting that "7.x and 8.x have different vector search APIs; determines adapter complexity." The 8.x reference appears only as a proposed mitigation in the Risks section, not as a decided target. The reviewer stated an unresolved question as a definitive scope commitment.

**Root cause:** Reviewer hallucination — the security reviewer read the 8.x mention in the risks/mitigation section and promoted it to a scoping decision. The STRAT explicitly leaves this as an open question. Same pattern as claim 4777 (cloud_id): the reviewer overstates what the proposal actually commits to.

**Pattern:** This is the second instance of reviewers converting hedged or open-ended language in proposals into definitive factual assertions. The security review agents appear to have a bias toward resolving ambiguity rather than preserving it.

### 6. Library vs container FIPS inheritance ambiguity (Claim 4771)

**Claim:** "ai4rag's FIPS compliance is inherited from the UBI 9 container base image."

**Verdict:** REFUTED (confidence 95%)

**Evidence:** The architecture docs state ai4rag is "a pure Python library with no container image" — it's `pip install`able, has no Dockerfile, and "inherits FIPS compliance from the container image of whatever service imports it." The reviewer assumed ai4rag is itself containerized on UBI 9, but it's a library consumed by other containers.

**Nuance:** The reviewer's underlying reasoning is sound — ai4rag's FIPS compliance *does* come from the runtime container's base image, and those containers do use UBI 9. The claim is directionally correct but states something imprecise: ai4rag doesn't have "a UBI 9 container base image" because it has no container image at all. It inherits FIPS from whatever container imports it.

**Significance:** This highlights an architectural documentation gap. The arch docs clearly state ai4rag is a library, but the STRAT's security section doesn't clarify the deployment model. When the reviewer sees "FIPS compliance" requirements applied to ai4rag, the natural assumption is that it's a container — because most RHOAI components are. The fix may not be in the reviewer prompt but in the STRAT template: strategy authors should specify whether a component is a library, a container, or an operator, so downstream reviewers don't have to guess.

### 7. Reviewer fabricates security rationale from training knowledge (Claim 4732)

**Claim:** "Elasticsearch 7.x did not enable security features by default."

**Verdict:** REFUTED (confidence 95%)

**Evidence:** The STRAT mentions "Target Elasticsearch 8.x as minimum" as a mitigation for version fragmentation, but the stated reason is vector search API differences (`knn` query support in 8.x vs older APIs in 7.x). The STRAT never discusses Elasticsearch security feature defaults. The reviewer introduced this detail from training knowledge to support a risk finding about version selection.

**Root cause:** Training knowledge injection. The reviewer connected two unrelated facts: "8.x is the target version" (from the STRAT) + "7.x didn't enable security by default" (from training knowledge) → fabricated a security rationale the STRAT never makes. The actual 8.x rationale is about vector search capabilities, not security defaults.

**Pattern:** This is a pure `training_knowledge` hallucination — the reviewer added externally-sourced context that sounds plausible and may even be factually correct, but is not grounded in the source material. The claim cannot be verified from the evidence available to the reviewer; it was stated as supporting fact without attribution.

### 8. Architecture doc gap: AutoRAG backend service (Claim 4781)

**Claim:** "No dedicated architecture document exists for the AutoRAG backend."

**Verdict:** SUPPORTED (confidence 95%) — likely correct.

**Evidence:** The verifier searched `search AutoRAG`, `list --names-only`, `grep autorag`, and `component odh-dashboard -o raw`. No standalone "AutoRAG backend" component exists in architecture-context. The closest match is `ai4rag`, but that documents the optimization *library* (a pip-installable Python package), not the backend *service* that hosts vector store adapters and pipeline orchestration. The STRAT itself distinguishes them: "Components: AutoRAG backend, odh-dashboard (autorag-ui plugin)" — the backend service is a separate component from the library it consumes.

**Significance:** This is a genuine architecture documentation gap, not a hallucination. The AutoRAG backend service — the thing that would host the Elasticsearch adapter, manage pipeline specs, and coordinate with odh-dashboard — has no architecture doc. The `ai4rag` library doc covers the optimization engine but not the service layer. The `autorag-ui` module is documented as part of odh-dashboard but the backend it talks to is undocumented.

**Candidate for architecture-context coverage:** The AutoRAG backend service needs its own component doc in architecture-context, separate from `ai4rag` (the library) and `autorag-ui` (the dashboard module).

### 9. Reviewer fabricates major version bump (Claim 4524)

**Claim:** "The strategy involves upgrading Transformers from version 4.x to 5.x"

**Verdict:** REFUTED (confidence 100%)

**Evidence:** The source STRAT (RHAISTRAT-1876) clearly states the upgrade is from `transformers==5.5.3` to `transformers>=5.6.0` — a minor version bump within 5.x. The reviewer invented a major version jump from 4.x to 5.x that the source text never describes.

**Root cause:** Training knowledge injection or careless summarization. The reviewer may have known that Transformers 4.x → 5.x was a significant industry event and assumed this STRAT was about that transition. Or the reviewer simply misread the version numbers. Either way, the claim directly contradicts the source text.

**Pattern:** Unlike the subtler findings (cloud_id storage, Elasticsearch security defaults), this is a straightforward factual error — the version numbers are explicitly stated in the source and the reviewer got them wrong. No ambiguity, no interpretation required.

### 10. Proposed deliverable stated as existing fact (Claim 4394)

**Claim:** "New GPU-enabled container images for OVMS and MLServer are built via the Konflux pipeline."

**Verdict:** REFUTED (confidence 95%)

**Evidence:** The verifier checked both components in arch-query. MLServer's Konflux build uses a CPU-only base image (`quay.io/aipcc/base-images/cpu:3.5.0-ea.1`). No GPU-enabled images exist for either OVMS or MLServer. The source RFE (RHAIRFE-2324) requests GPU support as a feature gap — the STRAT proposes to create these images, not describes existing ones.

**Root cause:** Source confusion. The strat-pipeline generated a task description that presents a proposed deliverable ("New GPU-enabled container images... are built via Konflux") in present tense, as if it already exists. The claim extractor faithfully captured it. The verifier correctly identified the discrepancy by checking actual build artifacts in architecture docs.

**Pattern:** The strat-pipeline's AI-generated strategy section (under "Architecture Fit") uses present tense for proposed work: "New container images for GPU-enabled OVMS and MLServer are built via the existing Konflux pipeline." This is not a task description or acceptance criteria — it's the strategy narrative itself describing the proposed architecture as if it already exists. The claim extractor pulled it verbatim. This present-tense-for-proposals pattern in the strat-pipeline's output is a systemic source of extractable false claims.

### 11. NFR checklist missing business rationale for FIPS (Claim 4813)

**Claim:** "FIPS 140-3 compliance is an RHOAI organizational constraint for FedRAMP and government customers."

**Verdict:** INCONCLUSIVE (confidence 70%)

**Evidence:** The NFR checklist states "FIPS 140-3: all crypto uses FIPS-validated modules on RHEL 9" — confirming FIPS is mandatory but not stating *why*. The FedRAMP and government customer rationale is almost certainly correct but isn't in any source material available to the reviewer.

**Root cause:** Second NFR checklist gap (see also finding #4). The checklist defines *what* is required but not *why*. The reviewer filled in the business context from training knowledge. Adding a rationale line to the checklist ("Required for FedRAMP authorization and government customer deployments") would ground this claim and prevent reviewers from needing to inject business context.

**Pattern:** The NFR checklist is a recurring source of partially-grounded claims. Reviewers consistently enrich checklist items with context that's likely correct but unverifiable from available evidence. The fix is the same each time: make the checklist more complete so reviewers don't need to supplement it.

### 12. Verification uncovers real platform compliance gap: spark-operator FIPS (Claim 4329)

**Claim:** "All Go operators on the RHOAI platform use the FIPS build pattern with CGO_ENABLED=1 and GOEXPERIMENT=strictfipsruntime on UBI 9."

**Verdict:** REFUTED (confidence 95%)

**Evidence:** The verifier checked six Go operators individually via `arch-query component -o raw`:
- rhods-operator: CGO_ENABLED=1 ✓
- training-operator: CGO_ENABLED=1 ✓
- codeflare-operator: CGO_ENABLED=1 ✓
- model-registry-operator: CGO_ENABLED=1 ✓
- data-science-pipelines-operator: CGO_ENABLED=1 ✓
- **spark-operator: CGO_ENABLED=0 ✗** — static linking, no FIPS

The architecture docs explicitly note: "CGO_ENABLED=0 means Go binary uses pure-Go crypto, not OpenSSL. Will fail check-payload FIPS validation."

**Significance:** This is NOT a hallucination finding — it's a **compliance finding**. The reviewer correctly stated the NFR requirement ("all Go operators must use FIPS build pattern"). The verification system found a real component that violates that requirement. The claim is refuted only because spark-operator is non-compliant, not because the reviewer was wrong about what the requirement says.

**This is the observatory working as intended** — hallucination detection as a side effect discovered a genuine platform defect. The spark-operator team should be notified that their build flags don't meet the FIPS NFR.

### 13. Architecture-context misattributes authentication to kube-rbac-proxy (Claim 3900)

**Claim:** "SubjectAccessReview authorization via kube-rbac-proxy is the RBAC enforcement pattern used across all dashboard BFF modules."

**Verdict:** REFUTED by Claude (confidence 95%), INCONCLUSIVE by Codex (confidence 72%) — both wrong, claim is correct.

**Evidence:** The architecture-context raw output states: "The authentication architecture is layered: kube-rbac-proxy handles the initial authentication (extracting user identity from Gateway/OAuth headers)." This is factually incorrect. kube-rbac-proxy does NOT perform authentication — it performs SubjectAccessReview authorization using the identity header passed to it by Envoy + kube-auth-proxy. Authentication happens upstream.

The actual auth chain is: Envoy → kube-auth-proxy (authentication, identity extraction) → kube-rbac-proxy (SAR authorization check) → backend/BFF. The architecture-context docs conflate authentication and authorization, misattributing the authentication step to kube-rbac-proxy.

**Root cause:** Architecture-context documentation error. The generated arch doc for odh-dashboard incorrectly describes kube-rbac-proxy as handling "initial authentication." This is a factual error in the ground truth — kube-rbac-proxy is a SAR checker only. The reviewer's original claim ("SubjectAccessReview authorization via kube-rbac-proxy") is actually MORE accurate than the architecture docs.

**Significance:** This is the second finding (after #4, NFR checklist) where the ground truth documentation itself contains errors. Both verifiers (Claude and Codex) were misled by the incorrect arch docs. The architecture-context generator needs to correctly distinguish authentication (kube-auth-proxy) from authorization (kube-rbac-proxy) in the odh-dashboard component doc.

**Source file:** `var/checkouts/architecture-context/architecture/rhoai.next/odh-dashboard.md`

**Cross-engine comparison:** Same claim, same skill, same evidence — three different verdicts:
- Claude Opus: **refuted** (95%) — confidently wrong
- Codex gpt-5.5 run 1: **inconclusive** (72%) — hedged, more honest
- Codex gpt-5.5 run 2: **supported** (82%) — correct

The non-determinism highlights that multi-layer architectural reasoning is at the edge of what current models can reliably do. Claude committed confidently to the wrong answer; Codex hedged first, then got it right on the second run. Neither model was consistently correct, but Codex's lower confidence was more calibrated — it correctly signaled uncertainty when the evidence was complex.

**Candidate for overlay:** An architecture-context overlay should correct the authentication attribution for odh-dashboard, clarifying that kube-rbac-proxy performs SAR authorization, not authentication.

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
