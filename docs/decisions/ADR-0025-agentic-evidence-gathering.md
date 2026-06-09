# ADR-0025: Agentic Evidence Gathering via Claude Code Skill

## Status

Proposed

## Context

The hallucination verification system (ADR-0022) uses a two-step process: (1) deterministic Python code gathers evidence, (2) an LLM judge evaluates the claim against that evidence. The problem is in step 1 — the evidence gathering is only as good as its hardcoded patterns.

### What's wrong with deterministic evidence gathering

The `find_source_material` function in `verify-claims.py` decides what to look up using:

- **Component name extraction** (`_extract_component_names`) — substring-matches the claim text against a cached component list and a manually maintained alias dict. If the claim says "MLflow Operator" but the component is `mlflow-operator`, or uses a name not in `_component_aliases`, no architecture lookup happens.

- **Hardcoded grep terms** — a regex on line 383 triggers arch-query grep for exactly 7 patterns: `OGX|port \d+|mTLS|FIPS|certifi|kube-rbac-proxy|NetworkPolicy`. Any claim about webhooks, CRDs, container images, dependencies, or other architectural concepts gets zero grep-based evidence.

- **Unused arch-query subcommands** — the `arch-query` CLI has 18 subcommands (`component`, `crds`, `deps`, `diff`, `grep`, `images`, `list`, `overlays`, `platform`, `ports`, `search`, `watches`, `webhooks`, etc.) but only 3 are used in evidence gathering. A claim like "training-operator has 6 validating webhooks" gets no webhook-specific evidence because the `webhooks` subcommand is never called.

The LLM judge returns "insufficient" not because the evidence doesn't exist, but because the Python code didn't find it. The judge never gets to say "I need to check the webhooks for training-operator" — it only sees whatever the deterministic code happened to retrieve.

### Why not expand the patterns?

Adding more regex patterns and subcommand calls is a losing game. Every new claim type requires new patterns. The fundamental issue is that a static program cannot anticipate what evidence an arbitrary claim needs — that's a judgment call that belongs to the LLM.

### What we learned from ADR-0024

ADR-0024 proposed tracing hallucination root causes through agent execution logs. Investigation revealed that:

1. All pipelines with refuted claims (strat-pipeline, strat-security-reviews) store reasoning in artifact files, not traces
2. The artifact files are already read during verification as warmup evidence
3. A separate root cause tracing phase would read the same files we already read

This means root cause classification can be embedded in the verification step itself — the judge already sees the agent's output. What it needs is better access to the architecture ground truth.

## Decision

Replace the deterministic evidence-gathering approach with a Claude Code skill that lets the LLM judge gather its own evidence. The verification script invokes `claude -p` for each claim, and Claude Code uses Bash (for arch-query) and Read (for raw docs) to investigate before rendering a verdict.

### Architecture

```
verify-claims.py (orchestrator)
    |
    ├── Query DB for pending claims
    ├── For each claim (parallel, 3 workers):
    │   ├── Gather warmup evidence (co-located files only)
    │   ├── Write claim + warmup to /tmp/verify-claim-{id}.json
    │   ├── Invoke claude.vertex -p "..." with verify-claim skill
    │   ├── Parse JSON verdict from stdout
    │   └── Write verdict to DB + verification log
    └── Report summary
```

### Why Claude Code instead of SDK tool_use

Claude Code already has:
- Bash tool for running `arch-query` subcommands
- Read tool for examining raw architecture docs
- Grep tool for searching across files
- Permission controls via `--allowed-tools`
- `--output-format json` for structured output
- Proven at scale in the CI pipelines this observatory monitors

Building a custom tool_use loop with the Anthropic SDK would duplicate capabilities that already exist.

### The skill

`.claude/skills/verify-claim/SKILL.md` teaches Claude how to:
- Read the claim input file
- Evaluate warmup evidence first (skip tools if evidence is sufficient)
- Use arch-query subcommands via Bash when more evidence is needed
- Read raw architecture docs when arch-query results are insufficient
- Distinguish source documents (proposals) from architecture docs (current state)
- Detect RHOAI version references and query the appropriate version
- Return a structured JSON verdict with optional root cause classification

### Mode flag

The `--mode` argument to `verify-claims.py` controls behavior:

- `deterministic` (default) — current behavior, no changes
- `agentic` — Claude Code skill for architectural/security claims, deterministic for others
- `agentic-retry` — only re-verify claims with "insufficient" or "inconclusive" verdicts

### Warmup evidence (simplified)

In agentic mode, `find_source_material` is simplified to file-based evidence only:
- Co-located artifact files (strat-text, threat-surface, strat-originals)
- NFR checklist (for security claims)

All arch-query calls, component name extraction, grep patterns, and platform summary lookups are removed from the Python code — the skill handles them.

### Root cause classification (replaces ADR-0024 Phase 3)

For refuted claims, the skill also classifies the root cause:
- **reasoning_error** — agent had correct info but drew wrong conclusions
- **information_gap** — agent lacked data and filled in from training knowledge
- **source_confusion** — agent confused proposals with existing platform state
- **stale_data** — agent used outdated architecture information
- **training_knowledge** — agent stated training knowledge as platform fact

This replaces the separate root cause analysis phase proposed in ADR-0024.

## Consequences

Positive:
- Evidence gathering adapts to claim content instead of relying on hardcoded patterns
- All 18 arch-query subcommands become available without Python-level anticipation
- The `_component_aliases` dict, hardcoded grep regex, and keyword-triggered queries become unnecessary for agentic mode
- Root cause classification happens in the same pass as verification
- Reuses Claude Code infrastructure proven in CI pipelines

Negative:
- Cost per claim increases from 1 Sonnet API call to 1 Claude Code session (~3-8 tool calls)
- Latency per claim increases from ~2s to ~15-30s (Claude Code startup + tool calls)
- Requires `claude` CLI installed and configured for Vertex AI
- Worker count reduced from 5 to 3 to stay within rate limits
- `--mode agentic-retry` recommended workflow mitigates cost: deterministic first pass, agentic on failures only

## References

- ADR-0022 (Single Verdict Per Claim) — the aggregated evidence approach this builds on
- ADR-0024 (Hallucination Root Cause Tracing) — the root cause analysis this replaces
- `var/definitions/epic-decomposer/source-repo/scripts/run-claude.sh` — proven pattern for non-interactive Claude Code invocation
