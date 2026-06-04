# M2: Live Status

**Phase:** 2 — Pull Collector + Live Status
**Status:** Pending

## Definition

The collector is running and populating run history from CI APIs. Status board shows real green/yellow/red health indicators. Pipeline detail shows run history.

## Key Results

- [ ] Collector polls GitLab CI and GitHub Actions on schedule
- [ ] `pipeline_runs` table populated with real run data
- [ ] Health status computed correctly (green/yellow/red/grey)
- [ ] Status board shows colored health dots
- [ ] Pipeline detail shows run history table and duration chart
- [ ] Admin page shows collector state
