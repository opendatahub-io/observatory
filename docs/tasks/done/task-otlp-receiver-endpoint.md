# Task: OTLP HTTP Receiver Endpoint

## Goal

Implement `POST /v1/traces` to accept OTLP HTTP telemetry data (JSON and protobuf).

## Context

Uses `opentelemetry-proto` Python package for Pydantic-compatible OTLP models. Parses spans, extracts token/cost/duration metrics, stores in `telemetry_spans`, and computes `telemetry_summaries`.

## Acceptance Criteria

- [ ] `POST /v1/traces` accepts OTLP HTTP JSON (`application/json`)
- [ ] `POST /v1/traces` accepts OTLP HTTP protobuf (`application/x-protobuf`)
- [ ] Parses spans: trace_id, span_id, parent_span_id, operation_name, service_name, attributes, duration
- [ ] Stores in `telemetry_spans`
- [ ] Computes and stores `telemetry_summaries` from span attributes (tokens, cost, model, skill)
- [ ] Returns standard OTLP response
- [ ] Tests with sample OTLP payloads

## Files Likely Involved

- backend/routers/otlp.py
- backend/parsers/otlp.py
- tests/test_otlp_receiver.py

## Phase

4 — OTLP Push Receiver

## Status

Pending
