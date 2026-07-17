# Semantic Claim Consolidation Baseline

**Dataset revision:** `semantic-claim-equivalence-v1`
**Retrieval baseline:** token overlap with the reviewed alias map, threshold 0.20
**Decision policy:** conservative structured exclusions; all other pairs abstain

## Results

The first versioned sample contains 12 labeled pairs: five equivalent, three
related, three distinct, and one needing review. It includes the `rhai-cli`
cluster, explicit version changes, opposite negation, fact versus requirement,
document versus platform scope, known aliases, cross-artifact repetition, and a
one-way implication.

- Candidate volume: 11 of 12 labeled pairs.
- Equivalent-pair retrieval recall: 5 of 5 (100%).
- Equivalent-pair automatic predictions: 0.
- Automatic equivalent precision: not measurable because the conservative
  policy abstained on every possible equivalent.
- Estimated repeated verification pairs in the sample: 5.
- Sample equivalent-pair rate: 5 of 12 (41.7%); this is a deliberately enriched
  regression sample and must not be reported as a production duplicate rate.

The 0.25 threshold retrieved only four of five equivalent pairs (80% recall).
The 0.20 threshold is therefore the lexical regression baseline. Observatory's
runtime FTS5 retrieval remains bounded by shortlist size and records its own
BM25 query, score, and revision; production recall must be measured after a
representative database backfill.

No automatic grouping is authorized by this baseline. A zero-prediction class
does not satisfy the proposed 99% precision gate. Human-reviewed grouping is
enabled, and the automatic policy remains disabled with its kill switch on.

The audit output includes an `evaluation_record` object shaped for
`POST /api/v2/claim-consolidation/evaluations`. For this baseline, the record
has `equivalent_prediction_count: 0`, `precision: null`, `recall: 0`, and
`false_negative_count: 5`; it is suitable for audit history, not automatic
authorization.

## Production Baseline Availability

The repository's untracked `observatory.db` did not contain a `claims` table, so
it could not supply existing-claim counts without inventing or mutating data.
Run the read-only production audit against an initialized database:

```bash
uv run python scripts/audit-claim-consolidation.py \
  --database /path/to/observatory.db --threshold 0.20
```

Reproduce the checked-in sample measurement with:

```bash
uv run python scripts/audit-claim-consolidation.py \
  --dataset data/semantic-claim-equivalence-v1.json \
  --threshold 0.20 \
  --evaluation-run-id semantic-claim-equivalence-v1-baseline \
  --retrieval-revision token-overlap-threshold-0.20
```

Candidate generation metrics, qualifier decision counts, grouping rates,
review corrections, time-to-decision, verification agreement, and occurrence /
text-identity / canonical-group counts are available through
`GET /api/v2/claim-consolidation/metrics`, including artifact type, claim type,
extractor revision, and product-version breakdowns.
