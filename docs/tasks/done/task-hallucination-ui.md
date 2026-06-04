# Task: Hallucination Detection UI

## Goal

/hallucinations page with dashboard and claim browser, plus sidebar nav entry.

## Acceptance Criteria

- [ ] Sidebar entry "Hallucinations" in Observability section (with AlertTriangle icon)
- [ ] Route at /hallucinations
- [ ] Summary cards: total claims, supported, refuted, pending, inconclusive
- [ ] Refutation rate by pipeline (bar chart)
- [ ] Filterable claim table: pipeline, type, verdict, confidence
- [ ] Expandable claim detail: full text, original context, evidence, verdict reasoning
- [ ] Pipeline detail page shows hallucination summary card with link

## Files Involved

- src/frontend/src/pages/Hallucinations.tsx (new)
- src/frontend/src/App.tsx (route)
- src/frontend/src/components/Sidebar.tsx (nav entry)
- src/frontend/src/Layout.tsx (page title)
- src/frontend/src/pages/PipelineDetail.tsx (summary card)

## Status

Pending

## blockedBy

- task-hallucination-api.md
