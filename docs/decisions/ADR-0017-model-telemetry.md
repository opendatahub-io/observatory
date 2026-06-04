# ADR-0017: Model Usage Telemetry

## Status

Accepted

## Context

The OTEL data from Claude Code CI jobs contains rich per-data-point attributes that break down cost and token usage by multiple dimensions. The current ingestion (ADR-0016) only captures aggregate totals per run. The raw data supports much more granular analysis.

Available attributes on `claude_code.cost.usage` and `claude_code.token.usage` metrics:

| Attribute | Values Seen | Insight |
|-----------|------------|---------|
| `model` | `claude-opus-4-6` | Which model is used (currently uniform, but will diverge as pipelines adopt different models) |
| `query_source` | `main`, `subagent` | Main agent vs subagent token/cost split |
| `agent.name` | `custom` | Agent type classification |
| `plugin.name` | `third-party` | Which plugin/skill is driving the cost |
| `skill.name` | `third-party` | Skill attribution |
| `effort` | `high` | Effort level setting |
| `type` (on tokens) | `input`, `output` | Input vs output token breakdown |

Additional metrics with their own attributes:
- `claude_code.lines_of_code.count` with `type=added|removed` — code churn
- `claude_code.code_edit_tool.decision` with `language`, `tool_name` — what tools and languages the agent works with
- `claude_code.session.count` with `start_type=fresh` — session lifecycle

## Decision

Extend the telemetry ingestion to extract per-dimension breakdowns and store them in a new `telemetry_dimensions` table. Update the telemetry page to show:

### New table

```sql
CREATE TABLE telemetry_dimensions (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    dimension_key TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE INDEX idx_telemetry_dims_run ON telemetry_dimensions(pipeline_run_id);
CREATE INDEX idx_telemetry_dims_metric ON telemetry_dimensions(metric, dimension_key);
```

### Dimensions to extract per run

From `claude_code.cost.usage`:
- `model` — cost by model
- `query_source` — cost by main vs subagent

From `claude_code.token.usage`:
- `model` — tokens by model
- `type` — input vs output tokens
- `query_source` — tokens by main vs subagent

From `claude_code.lines_of_code.count`:
- `type` — lines added vs removed

### Telemetry page additions

- **Model usage card** — which models are in use, cost/tokens per model
- **Main vs Subagent split** — pie or stacked bar showing what fraction of cost/tokens goes to subagents
- **Input vs Output tokens** — ratio visualization
- **Code churn** — lines added/removed per pipeline

### Queries enabled

- `SELECT dimension_value, SUM(value) FROM telemetry_dimensions WHERE metric = 'cost' AND dimension_key = 'model' GROUP BY dimension_value` — cost by model across all runs
- Same pattern for tokens by model, tokens by input/output, cost by main/subagent

## Consequences

Positive:
- Model migration tracking — when pipelines switch from opus to sonnet, the cost impact is immediately visible
- Subagent cost visibility — understand the overhead of multi-agent workflows
- Input/output token ratio — identify chatty vs efficient pipelines
- Foundation for cost optimization recommendations

Negative:
- More rows in the database (multiple dimension rows per run per metric)
- OTEL attribute format may change across Claude Code versions
- Currently all pipelines use `claude-opus-4-6` — model dimension won't be interesting until pipelines diverge
