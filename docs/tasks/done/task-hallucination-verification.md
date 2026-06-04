# Task: Claim Verification Script

## Goal

Batch script that verifies extracted claims against source material in the artifact directories.

## Acceptance Criteria

- [ ] scripts/verify-claims.py processes unverified claims from the DB
- [ ] Locates source material co-located with the output file (e.g., *-strat-text.md for security reviews)
- [ ] LLM-as-judge evaluates claim against source text
- [ ] Verdict assigned: supported / refuted / insufficient / inconclusive
- [ ] Confidence score 0-100
- [ ] Evidence summary and source reference stored
- [ ] make verify-claims target

## Files Involved

- scripts/verify-claims.py (new)

## Status

Pending

## blockedBy

- task-hallucination-extraction.md
