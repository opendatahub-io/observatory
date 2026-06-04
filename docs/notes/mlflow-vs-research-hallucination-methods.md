# MLflow Hallucination Tooling vs. Research Methodologies

Comparison of MLflow's built-in hallucination detection capabilities against the methodologies described in the reference PDFs in `docs/references/`.

---

## Summary of Research Methodologies

### 1. Semantic Entropy (Farquhar et al., Nature 2024)

**Core idea:** Sample multiple responses from an LLM for the same prompt, cluster them by semantic meaning (using NLI-based bidirectional entailment), then compute entropy over the meaning clusters. High semantic entropy = the model is uncertain = likely confabulating.

**Key properties:**
- Unsupervised -- requires no labeled data or task-specific training
- Works at the *meaning* level, not token level (unlike naive entropy which treats "Paris" and "France's capital Paris" as different)
- Achieves 0.790 AUROC averaged across 30 task/model combinations
- Detects *confabulations* specifically (arbitrary, wrong answers sensitive to random seeds), not systematic errors
- Extends to paragraph-length biographies via factoid decomposition (FactualBio dataset)
- Requires 5-10 generation samples per input, making it 5-10x more expensive than single-generation methods

### 2. Semantic Entropy Probes (Kossen et al., 2024)

**Core idea:** Train lightweight linear probes on LLM hidden states to *predict* semantic entropy from a single forward pass, eliminating the need for multiple samples.

**Key properties:**
- Linear logistic regression on hidden states at specific layers/token positions
- Reduces the computational overhead of semantic entropy to near-zero at inference
- Generalizes better to unseen tasks than accuracy-trained probes (AUROC improvement of +7.7 to +10.5 on out-of-distribution tasks)
- Requires access to model internals (hidden states) -- incompatible with closed-source / API-only models
- Works *before* generating any tokens (token-before-generation variant)

### 3. Claimify (Metropolitansky & Larson, ACL 2025)

**Core idea:** Extract factual claims from LLM-generated text through a multi-stage pipeline: sentence splitting, selection (verifiable content only), disambiguation (resolve referential and structural ambiguity), and decomposition into atomic claims.

**Key properties:**
- Addresses a *prerequisite* step for hallucination detection -- you can't verify claims you haven't extracted correctly
- Explicitly handles ambiguity (referential and structural) -- labels unresolvable ambiguity as "Cannot be disambiguated" rather than guessing
- Evaluated on entailment (99%), coverage (87.9% element-level accuracy), and decontextualization (80.5% desirable outcomes)
- Outperforms VeriScore, DnD, SAFE, AFaCTA, and Factcheck-GPT baselines
- Operates on long-form QA answers (BingCheck dataset)

### 4. VeriTrail (Metropolitansky & Larson, ICLR 2026)

**Core idea:** Closed-domain hallucination detection with *traceability* -- not just whether the output is faithful, but *where* in a multi-step generative process the hallucination was introduced.

**Key properties:**
- Models generative processes as DAGs (nodes = text spans, edges = input-output relationships)
- Handles both single generative step (SGS, e.g., RAG) and multiple generative step (MGS, e.g., hierarchical summarization, GraphRAG) processes
- Provides provenance (evidence trail through intermediate nodes to source) and error localization (which stage introduced the hallucination)
- Uses Claimify for claim extraction, then iteratively walks the DAG: sub-claim decomposition, evidence selection, verdict generation, candidate node selection
- Three verdicts: Fully Supported, Not Fully Supported, Inconclusive
- Outperforms RAG, AlignScore, INFUSE, Bespoke-MiniCheck-7B, Gemini 1.5 Pro, and GPT-4.1 Mini on both FABLES+ and DiverseSumm+ datasets (Macro F1: 84.5 on FABLES+, 79.5 on DiverseSumm+)

### 5. Datadog LLM-as-a-Judge (blog post, Aug 2025)

**Core idea:** Use structured rubric-based prompting with LLM judges to detect hallucinations in RAG applications, focusing on faithfulness (does the answer agree with the retrieved context?).

**Key properties:**
- Rubric-based approach: the judge fills out a structured "disagreement claims" rubric with context quotes, answer quotes, reasoning, and disagreement type
- Distinguishes **contradictions** (claims directly opposing context) from **unsupported claims** (claims not grounded in context)
- Two-step prompting: (1) free-text reasoning from a large LLM, (2) structured output extraction from a smaller LLM -- emulates reasoning model behavior without dedicated reasoning models
- Achieves F1 of 0.810 on HaluBench and RAGTruth benchmarks
- Designed for production monitoring at scale (black-box, no model internals needed)

### 6. Braintrust Hallucination Tools Survey (May 2026)

**Overview article** comparing five hallucination detection tools (Braintrust, Galileo, Arize Phoenix, Patronus AI, Promptfoo) across three operating modes:
- **Pre-deployment evaluation** -- golden test sets, groundedness/factuality scoring before release
- **Production monitoring** -- scoring live traces, sampling, drift detection
- **Runtime guardrails** -- inline blocking/routing of high-risk responses

Key detection methods surveyed: LLM-as-a-judge, semantic entropy / consistency sampling, embedding similarity / groundedness checks, fine-tuned detection models (Lynx, Luna-2), human-in-the-loop annotation.

---

## MLflow's Approach

MLflow implements hallucination detection exclusively via **LLM-as-a-judge** and **NLI-based groundedness scoring**, offered through built-in judges and third-party scorer integrations:

| Component | Method | Location |
|---|---|---|
| `is_grounded()` | LLM judge with structured prompt | `mlflow/genai/judges/builtin.py` |
| `RetrievalGroundedness` | Built-in scorer wrapping `is_grounded()` | `mlflow/genai/scorers/builtin_scorers.py` |
| `faithfulness()` | LLM judge evaluating factual consistency | `mlflow/metrics/genai/metric_definitions.py` |
| DeepEval `Hallucination` | Third-party scorer (v3.8.0) | `mlflow/genai/scorers/deepeval/` |
| Phoenix `Hallucination` | Third-party scorer (v3.9.0) | `mlflow/genai/scorers/phoenix/` |
| Google ADK `Hallucination` | Wraps `HallucinationsV1Evaluator` (v3.11.0) | `mlflow/genai/scorers/google_adk/` |
| DeepEval `Faithfulness` | Groundedness in retrieval context | `mlflow/genai/scorers/deepeval/scorers/rag_metrics.py` |
| RAGAS `Faithfulness` | RAG faithfulness evaluation | `mlflow/genai/scorers/ragas/` |
| RAGAS `ResponseGroundedness` | Response grounded in retrieved context | `mlflow/genai/scorers/ragas/` |
| TruLens `Groundedness` | Chain-of-thought groundedness (v3.10.0) | `mlflow/genai/scorers/trulens/` |

All operate in the same paradigm: given (question, context, answer), ask an LLM or NLI model whether the answer is supported by the context.

---

## Gap Analysis: What MLflow Covers vs. What Research Proposes

### Covered by MLflow

| Capability | Research Equivalent | Notes |
|---|---|---|
| LLM-as-a-judge faithfulness | Datadog rubric approach | MLflow's `is_grounded()` prompt is simpler than Datadog's rubric but follows the same pattern |
| RAG groundedness scoring | Datadog, Braintrust survey | Core use case, well-supported through multiple scorer integrations |
| Multiple scorer backends | Braintrust survey recommendation | MLflow integrates DeepEval, Phoenix, RAGAS, TruLens, Google ADK |
| Pre-deployment evaluation | Braintrust survey | Via `mlflow.genai.evaluate()` |
| Production trace scoring | Braintrust survey | Via scheduled scorers on production traces |
| Human feedback collection | Braintrust survey | Via trace assessment APIs |

### NOT Covered by MLflow

| Research Method | Gap | Why It Matters |
|---|---|---|
| **Semantic entropy** (Farquhar et al.) | No implementation. MLflow has no mechanism to sample multiple generations, cluster by meaning, or compute entropy over semantic equivalence classes. | Semantic entropy is unsupervised, task-agnostic, and achieves 0.790 AUROC without any labeled data. It detects confabulations that LLM judges miss because it measures the model's own uncertainty rather than relying on a separate judge model. |
| **Semantic entropy probes** (Kossen et al.) | No implementation. Would require access to model hidden states and probe training infrastructure. | Reduces SE computation cost to near-zero. Best generalization to unseen tasks (+7-10 AUROC points vs. accuracy probes). Not feasible for API-only models, but valuable for self-hosted deployments. |
| **Claim extraction / decomposition** (Claimify) | No equivalent. MLflow's judges evaluate the full response as a unit. No pipeline to extract atomic, decontextualized, disambiguated claims first. | Without proper claim extraction, judges evaluate vague compound statements rather than precise atomic claims. Claimify shows that claim quality directly impacts verification accuracy. |
| **Multi-step traceability** (VeriTrail) | No equivalent. MLflow's tracing captures spans but doesn't model generative processes as DAGs or trace hallucinations back through intermediate outputs. | For RAG and agentic pipelines, knowing *that* a hallucination occurred is less useful than knowing *where* in the pipeline it was introduced. VeriTrail's provenance and error localization are critical for debugging multi-step systems. |
| **Structured rubric with disagreement typing** (Datadog) | Partial. MLflow's `is_grounded()` returns yes/no, not a structured rubric distinguishing contradictions from unsupported claims. | The distinction between "contradicts context" and "not grounded in context" matters operationally -- contradictions are higher severity. Datadog's rubric also forces quote extraction, improving explainability. |
| **Two-stage reasoning prompting** (Datadog) | Not implemented. MLflow uses single-prompt evaluation. | Datadog's two-step approach (free-text reasoning then structured extraction) emulates reasoning model behavior and improves accuracy without requiring dedicated reasoning models. |
| **Runtime guardrails / inline blocking** (Braintrust survey) | Not implemented. MLflow evaluates after the fact, not inline. The AI Gateway has guardrail hooks but no built-in hallucination blocking. | Production systems need both async scoring (MLflow has this) and synchronous blocking for high-risk outputs (MLflow does not). |
| **Fine-tuned detection models** (Braintrust survey: Lynx, Luna-2) | Not implemented. All MLflow scorers use general-purpose LLMs or NLI models, not hallucination-specialized fine-tuned classifiers. | Fine-tuned detectors (Patronus Lynx, Galileo Luna-2) can be faster and cheaper than LLM-as-a-judge for high-volume production scoring. |

---

## Architectural Implications

### What MLflow does well

1. **Integration breadth** -- by wrapping DeepEval, Phoenix, RAGAS, TruLens, and Google ADK, MLflow gives users access to multiple scorer ecosystems through a single API.
2. **Lifecycle coverage** -- the combination of `mlflow.genai.evaluate()` (offline), scheduled scorers (online), and trace assessment APIs (human feedback) covers three of the four operating modes identified in the Braintrust survey.
3. **Tracing infrastructure** -- MLflow's OTel-native tracing captures spans, inputs, outputs, and latency. This is the *data foundation* that more sophisticated methods (VeriTrail-style DAG tracing, semantic entropy computation) could build on.

### What would require significant new work

1. **Semantic entropy** -- would need: (a) a multi-sample generation API, (b) NLI-based semantic clustering, (c) entropy computation over clusters. The discrete variant (no token probabilities needed) could work with API-only models. This is a fundamentally different paradigm from LLM-as-a-judge.
2. **Claim extraction** -- would need a Claimify-style pipeline as a preprocessing step before evaluation. This would improve all downstream judges but adds latency and LLM calls.
3. **DAG-based traceability** -- MLflow's tracing already captures span hierarchies. Extending this to model generative processes as DAGs (VeriTrail-style) and walk them for evidence selection would be a natural evolution but requires new data structures and algorithms.
4. **Inline guardrails** -- the AI Gateway is the natural insertion point, but hallucination detection is inherently expensive (requires context comparison). Fine-tuned lightweight classifiers (Lynx-style) would be needed for sub-200ms inline blocking.

---

## Key Takeaway

MLflow's hallucination detection is **production-practical but methodologically narrow**. It covers the LLM-as-a-judge / groundedness scoring paradigm thoroughly, with good integration breadth and lifecycle coverage. However, it does not implement any of the more sophisticated research methods: semantic entropy (model uncertainty quantification), claim decomposition (structured fact extraction), multi-step traceability (provenance through generative pipelines), or fine-tuned detection models (low-latency specialized classifiers). The research papers describe approaches that are complementary rather than competing -- semantic entropy catches confabulations that judges miss, Claimify improves the precision of what gets evaluated, and VeriTrail adds the "where" to the "whether" of hallucination detection.
