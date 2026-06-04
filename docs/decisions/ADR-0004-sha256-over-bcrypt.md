# ADR-0004: SHA-256 Hashing Over bcrypt/Argon2

## Status

Accepted

## Context

The RFC (Section 6.2) strongly recommends bcrypt or Argon2id for API key hashing — slow hash functions that resist offline brute-force after database compromise. Our implementation uses SHA-256 (fast hash).

The RFC's recommendation is primarily aimed at systems where keys have low entropy (user-chosen passwords, short tokens). For high-entropy keys (256 bits), the threat model is different.

## Decision

Keep SHA-256 for API key hashing. Do not use bcrypt/Argon2.

**Why:**

1. **High entropy eliminates brute-force risk.** With 256-bit keys, even SHA-256 is computationally infeasible to brute-force. There are 2^256 possible keys — no amount of GPU time changes this. Slow hashing protects weak secrets; our secrets aren't weak.

2. **Performance.** SHA-256 completes in microseconds. bcrypt/Argon2 are intentionally slow (100ms+). Every push endpoint request validates a key — adding 100ms per OTLP span batch or MLflow metric log is meaningful latency for a lightweight app.

3. **No salting complexity.** SHA-256 of a 256-bit random key is effectively unique without salting. bcrypt requires salt management.

4. **Precedent.** GitHub uses SHA-256 for their token format (Section 15.1 of the RFC). Their threat model is comparable.

**When to revisit:** If Observatory ever accepts user-chosen keys (it shouldn't) or reduces key entropy below 128 bits, switch to Argon2id.

## Consequences

- Key validation is fast (~microseconds, no auth latency)
- No salt column needed in `api_keys` table
- If the database is compromised AND an attacker has unlimited compute, they still can't reverse 256-bit keys via SHA-256
- Simpler implementation with no bcrypt/Argon2 dependency
