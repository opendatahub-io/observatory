# ADR-0024: Hallucination Root Cause Tracing via Agent Execution Logs

## Status

Proposed

## Context

When the hallucination detection system refutes a claim, we currently know *what* was wrong but not *why* the agent produced it. For example:

- Claim: "training-operator has 6 validating webhooks" → Refuted (it has 5)
- Claim: "model-registry uses Istio mTLS" → Refuted (Istio is optional)
- Claim: "No existing reference to elasticsearch-py exists in the RHOAI platform architecture" → Initially mis-refuted because the verifier confused a proposal with existing state

In each case, understanding the root cause requires knowing what the agent was thinking, what tools it called, what data it received, and where its reasoning diverged from the ground truth.

### What we have

We collect three complementary data sources per pipeline run:

1. **Job traces** (ADR-0020, ADR-0021) — the full agent decision chain from GitLab CI logs:
   - `🧠 Thinking` blocks — the model's internal reasoning
   - `🔧 Bash $ command` — every tool call with the actual command
   - `💬 Claude response` — what the agent decided to do and why
   - `🤖 Agent [skill:agent] prompt` — subagent spawns with their prompts

2. **OTEL event logs** (ADR-0019) — structured telemetry per tool call:
   - `tool_decision` / `tool_result` — tool name, success/fail, duration, input/output sizes
   - `api_request` — model, tokens, cost, query_source (main/subagent)
   - `subagent_completed` — total tokens and tool uses per subagent
   - `compaction` — context window overflows and what was lost

3. **Architecture context** — the ground truth the agent should have used:
   - `arch-query` component fact sheets
   - Raw architecture markdown documents
   - Platform summary with authoritative counts

### What the academic literature says

**VeriTrail** (Metropolitansky & Larson, ICLR 2026) introduces **error localization** for multi-generative-step (MGS) processes — exactly what our agentic pipelines are. Their key insight:

> "For claims deemed 'Not Fully Supported,' the interim and final verdicts are used to identify error stage(s) — the stage(s) where the unsupported content was likely introduced."

VeriTrail traces backward through a DAG of generative steps, finding the last step where the claim was still supported before becoming unsupported. This pinpoints where the hallucination was *introduced*.

Our agent traces provide a richer version of this DAG — each thinking block, tool call, and subagent spawn is a generative step, and we have the actual content at each step.

**Braintrust** (2026) describes production hallucination debugging where engineers "move from a failed answer to the prompt, model call, retrieval step, tool output, latency, token usage, and cost data behind the failure." This is the observability angle — connecting a bad output to the execution context that produced it.

### What's novel

No existing tool or paper applies OTEL execution traces and CI job logs to hallucination root cause analysis. The academic work assumes access to intermediate generative outputs but not to the full execution trace with tool calls, reasoning, and subagent delegation. Our system has all three.

## Decision

Build a root cause tracing capability that connects refuted claims back to specific events in the agent execution trace. When a claim is refuted, the system identifies:

1. **Which run produced this claim** — link from claim source file → pipeline run → job trace
2. **What the agent was doing** — find the thinking/tool/response events temporally proximate to when the claim's source text was generated
3. **What information was available** — what tool calls returned data the agent used in its reasoning
4. **Where the error was introduced** — classify the root cause:
   - **Reasoning error** — the agent had correct information but drew wrong conclusions (e.g., counted 6 webhooks instead of 5)
   - **Information gap** — the agent lacked data and filled in from training knowledge (e.g., stated mTLS as fact when arch-query didn't mention it)
   - **Context overflow** — a compaction event lost relevant context before the claim was generated
   - **Source confusion** — the agent confused what's proposed (in the STRAT) with what currently exists (in the platform)
   - **Stale data** — the agent used an older version of architecture docs than what's current

### Reasoning location varies by pipeline

Not all pipelines expose reasoning in the same place:

| Pipeline | Reasoning Location | Format |
|----------|-------------------|--------|
| rfe-assessor | Job trace (thinking blocks, tool calls) | `🧠 Thinking`, `🔧 Bash $`, `💬 Claude` |
| rfe-autofixer | Job trace | Same emoji-delimited format |
| strat-pipeline | **Job trace (orchestration only) + artifact files (subagent output)** | Parent trace has `🤖 Agent`, `🔧 Skill` spawns; actual review reasoning is in `RHAISTRAT-*-review.md` artifacts |
| epic-decomposer | Job trace | Same |
| strat-security-reviews | **Artifact files themselves** | Reviewer markdown with DROPPED/KEPT rationale |
| autofix | Job trace (limited — Python orchestrator) | `run-batch.py` output, not `stream-claude.py` |

The security review pipeline is a special case: the reviewer markdown files contain the full decision chain. Each risk pattern is evaluated with explicit DROPPED/KEPT rationale explaining why. For example, claim 4748 ("elasticsearch-py is a pure HTTP client using Python's ssl module") was traced to reviewer-3's CRYPTO-03 analysis where it wrote:

> CRYPTO-03: DROPPED — The elasticsearch-py library is a pure HTTP client using Python's ssl module (which delegates to OpenSSL).

This reveals the root cause as **training knowledge application** — the reviewer characterized the library from its own knowledge, not from the source STRAT text. The claim is factually correct but not grounded in the source material.

The **strat-pipeline** follows a similar pattern: the parent job trace shows orchestration events (subagent spawns like `🤖 Agent Score RHAISTRAT-1857`, skill invocations like `🔧 Skill /strategy-architecture-review RHAISTRAT-1857`) but the actual review reasoning — the architectural analysis, feasibility assessment, and scope evaluation — is written by the subagent directly into `RHAISTRAT-*-review.md` artifact files. The parent trace never logs the subagent's internal thinking or tool calls.

For both security reviews and strat-pipeline, root cause analysis should search the reviewer artifact files for the claim text and extract the surrounding reasoning context, rather than looking at job traces.

### Implementation approach

**Phase 1: Link claims to runs**

Add `pipeline_run_id` to `claim_sources` (nullable, populated when we can match the source file path to a specific run). This enables jumping from a claim to the trace events for that run.

**Phase 2: Temporal correlation**

When a claim's source file is from a specific pipeline run, find the trace events (thinking blocks, tool calls, subagent spawns) that were active during the time window when the source file was being generated. The job trace has timestamps on every line — we can narrow down which agent actions led to the claim.

**Phase 3: Root cause classification**

For each refuted claim, run a focused LLM analysis:
- Input: the refuted claim + the verdict evidence + the relevant trace events from the run
- Output: a root cause classification (reasoning error, information gap, context overflow, source confusion, stale data) with a one-paragraph explanation

This is a second-pass analysis — only run on refuted claims, not all 30k claims.

**Phase 4: UI integration**

Add a "Root Cause" section to the claim detail in the hallucinations UI:
- Show the classified root cause type
- Show the relevant trace events (thinking blocks, tool calls) that led to the error
- Link to the full job trace for deeper investigation

### Hopeful outcomes

1. **Pattern detection** — if most hallucinations are "information gap" type, the fix is improving the tools the agent has access to (better arch-query coverage, more reference data). If most are "reasoning error," the fix is prompt engineering or model selection.

2. **Pipeline-specific insights** — different pipelines may hallucinate for different reasons. The security reviewer may have "source confusion" issues (confusing proposals with existing architecture) while the strat pipeline may have "reasoning errors" (miscounting or misstating scope).

3. **Feedback loop** — root cause data can inform:
   - Which arch-query commands to add to the agent's toolset
   - Which prompt instructions need strengthening
   - Whether compaction settings need adjustment (if context overflow is common)
   - Whether subagent prompts need more context

4. **Measurable improvement** — track root cause distribution over time. As pipeline prompts are improved, the proportion of each root cause type should shift.

5. **Proactive detection** — once root cause patterns are established, detect high-risk conditions *before* the output is published (e.g., flag runs that had compaction events near claim generation, or runs where arch-query returned empty for referenced components).

## References

- Metropolitansky, B. & Larson, K. (2026). VeriTrail: Closed-domain hallucination detection with traceability for multi-generative-step processes. *ICLR 2026*. — Error localization via backward tracing through generative step DAGs.
- Braintrust. (2026). Best hallucination detection tools for LLM applications. — Production debugging pattern: "move from a failed answer to the prompt, model call, retrieval step, tool output behind the failure."
- ADR-0019 (Full OTEL Event Ingestion), ADR-0020 (Job Trace Collection), ADR-0021 (Job Trace Parsing) — the data sources that make this possible.

## Consequences

Positive:
- Transforms hallucination detection from "what's wrong" to "why it's wrong and how to fix it"
- Enables data-driven prompt engineering and tool improvement
- Novel application of execution traces to hallucination analysis — no existing tool does this
- Builds on data we already collect (no new collection infrastructure)

Negative:
- Root cause analysis requires another LLM pass per refuted claim (cost)
- Temporal correlation between trace events and output text is approximate — the agent may have generated text asynchronously from its tool calls
- Some root causes may be ambiguous (was it a reasoning error or an information gap if the agent had partial data?)
- Compaction events may make some trace sections unrecoverable
