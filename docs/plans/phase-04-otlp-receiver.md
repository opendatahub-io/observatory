# Phase 4: OTLP Push Receiver

**Estimate:** 2-3 days
**Milestone:** M4-push-receivers

## Goal

Implement `/v1/traces` OTLP HTTP endpoint so pipelines that can reach Observatory push telemetry data directly instead of relying on artifact scraping.

## Deliverables

- OTLP HTTP receiver endpoint (JSON + protobuf via `opentelemetry-proto`)
- Span parsing: extract trace_id, span_id, operation_name, attributes, duration
- Pipeline correlation: match incoming spans to registered pipelines by service name or resource attributes
- Storage in `telemetry_spans` + automatic computation of `telemetry_summaries`
- Trace explorer view (span waterfall for a specific run)
- Documentation for pipeline owners to switch OTEL exporter endpoint

## Tasks

- `task-otlp-receiver-endpoint.md`
- `task-span-pipeline-correlation.md`
- `task-trace-explorer-ui.md`

## Exit Criteria

- Sending OTLP HTTP traces to `/v1/traces` stores spans in the database
- Spans are correlated with the correct registered pipeline
- Trace explorer renders a span waterfall for a run with pushed traces
