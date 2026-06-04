# ADR-0014: Global Artifacts Viewer as First-Class Navigation Item

## Status

Accepted

## Context

The artifacts browser currently lives embedded inside each pipeline's detail page. This means:
- Users must navigate to a specific pipeline first, then scroll down to find artifacts
- No cross-pipeline artifact browsing — can't see all data repo files across pipelines at once
- No way to search for a file across all pipelines
- Artifacts are second-class citizens hidden below run history and CI configuration

Artifacts are a primary output of the agentic CI system. The data repos contain RFE assessments, strategy documents, security reviews — these are the actual work product that stakeholders care about.

## Decision

Move the artifacts browser out of PipelineDetail and into a dedicated top-level page at `/artifacts` with its own sidebar navigation entry, positioned above Telemetry in the Observability section.

The page shows:
- A pipeline selector or grouped view of all pipelines with artifacts
- File tree browser per pipeline (CI job artifacts + data repo files)
- File content viewer
- Cross-pipeline file search

The pipeline detail page retains a compact summary (artifact count + link to the full viewer filtered to that pipeline).

## Consequences

Positive:
- Artifacts are discoverable without knowing which pipeline produced them
- Cross-pipeline browsing enables finding related outputs (e.g., all security reviews)
- Consistent with the sidebar pattern — each major data category gets its own nav entry
- The pipeline detail page becomes more focused on run history and CI config

Negative:
- Another page to maintain
- Duplicates some UI from the existing embedded widget (file tree + viewer)
