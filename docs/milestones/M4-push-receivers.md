# M4: Push Receivers

**Phases:** 4 + 5 — OTLP + MLflow Push
**Status:** Pending

## Definition

Pipelines can push OTLP traces and MLflow data directly to Observatory. Trace explorer visualizes span data.

## Key Results

- [ ] `/v1/traces` accepts OTLP HTTP and stores spans
- [ ] MLflow REST API subset works with standard `mlflow` client
- [ ] Trace explorer renders span waterfall
- [ ] Pipeline owner documentation exists for both endpoints
