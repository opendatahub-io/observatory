# ADR-0005: No Checksum Suffix on API Keys

## Status

Accepted

## Context

The RFC (Section 5.5) recommends a CRC32 or similar checksum appended to API keys for typo detection — GitHub uses a 6-character checksum suffix on their tokens. This allows rejecting obviously-invalid keys before hitting the database.

## Decision

Do not add a checksum suffix to Observatory API keys.

**Why:**

1. **Keys are never typed by hand.** Observatory keys are copied from the admin UI into CI secrets (GitLab CI variables, GitHub Actions secrets). There's no manual-entry typo risk.

2. **Complexity vs. value.** Adding checksum generation, validation, and stripping before hashing adds code for a scenario that doesn't occur in practice.

3. **Hash lookup catches invalid keys anyway.** An invalid key hashes to a non-matching value and returns 401. The user experience is the same — "invalid key" — with or without a checksum.

**When to revisit:** If Observatory distributes keys through channels where manual transcription is common (printed recovery codes, phone dictation), add a CRC32 suffix.

## Consequences

- Simpler key format: `obs_` + hex chars, nothing else
- Invalid keys detected at hash-lookup time (database round-trip) rather than at format-validation time (no round-trip)
- No risk of checksum algorithm mismatch between key versions
