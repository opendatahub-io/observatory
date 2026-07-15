# Bug: Observatory Image Missing Admin Endpoints (RESOLVED)

## Problem

The deployed observatory image (built 2026-06-26) predated the admin `wipe-runtime-data` and `seed` endpoints added in commit `48aeb9d`. Both returned HTTP 405 (Method Not Allowed) when called from the end-to-end demo Markov workflow.

## Resolution

Commit `48aeb9d` was on `feature/chat-knowledgebase` but had not been merged to `main`. Cherry-picked onto `main`, then rebuilt and redeployed the observatory image via `make host-rebuild-observatory`. Both endpoints now return HTTP 200. The `ignore_status: [405]` workaround has been removed from `reset-services.yaml`.
