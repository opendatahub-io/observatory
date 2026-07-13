# Claim-assurance migration runbook

The claim-assurance schema is additive. `init_schema()` creates v2 tables,
adds any missing additive columns, and idempotently backfills each legacy
claim/source pair as a source occurrence. Legacy claim APIs remain available
during the transition.

Before deploying the schema, stop Observatory writes and make a consistent
SQLite backup:

```bash
sqlite3 observatory.db ".backup 'observatory.pre-claim-assurance.db'"
```

Start the upgraded service and confirm the v2 summary and a legacy page:

```bash
curl -f http://localhost:8000/api/v2/claims/summary
curl -f http://localhost:8000/api/hallucinations/summary
```

Rollback restores the backup rather than attempting destructive down-migration
of immutable histories:

```bash
sqlite3 observatory.db ".restore 'observatory.pre-claim-assurance.db'"
```

Retain the pre-migration backup until the UI and workflows exclusively consume
versioned verification runs. Re-running startup is safe: legacy backfill keys
and partial unique indexes prevent duplicate occurrences and historical runs.
