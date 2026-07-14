"""Tests for the shared job-filter helpers."""

import json

from backend.collector.job_filter import has_job_filters, matches_job_filter, parse_job_filters


# ---------------------------------------------------------------------------
# parse_job_filters
# ---------------------------------------------------------------------------


class TestParseJobFilters:
    def test_both_none(self):
        jobs, patterns = parse_job_filters({})
        assert jobs == []
        assert patterns == []

    def test_explicit_none_values(self):
        jobs, patterns = parse_job_filters({"jobs": None, "job_patterns": None})
        assert jobs == []
        assert patterns == []

    def test_json_string_with_values(self):
        pipeline = {
            "jobs": json.dumps(["autofix-rfe", "autofix-bugfix"]),
            "job_patterns": json.dumps(["iterate-*"]),
        }
        jobs, patterns = parse_job_filters(pipeline)
        assert jobs == ["autofix-rfe", "autofix-bugfix"]
        assert patterns == ["iterate-*"]

    def test_empty_json_arrays(self):
        pipeline = {
            "jobs": json.dumps([]),
            "job_patterns": json.dumps([]),
        }
        jobs, patterns = parse_job_filters(pipeline)
        assert jobs == []
        assert patterns == []

    def test_only_jobs_set(self):
        pipeline = {"jobs": json.dumps(["my-job"])}
        jobs, patterns = parse_job_filters(pipeline)
        assert jobs == ["my-job"]
        assert patterns == []

    def test_only_patterns_set(self):
        pipeline = {"job_patterns": json.dumps(["build-*"])}
        jobs, patterns = parse_job_filters(pipeline)
        assert jobs == []
        assert patterns == ["build-*"]

    def test_json_null_string(self):
        pipeline = {"jobs": "null", "job_patterns": "null"}
        jobs, patterns = parse_job_filters(pipeline)
        assert jobs == []
        assert patterns == []


# ---------------------------------------------------------------------------
# has_job_filters
# ---------------------------------------------------------------------------


class TestHasJobFilters:
    def test_empty_returns_false(self):
        assert has_job_filters([], []) is False

    def test_jobs_only(self):
        assert has_job_filters(["a"], []) is True

    def test_patterns_only(self):
        assert has_job_filters([], ["*"]) is True

    def test_both(self):
        assert has_job_filters(["a"], ["b-*"]) is True


# ---------------------------------------------------------------------------
# matches_job_filter
# ---------------------------------------------------------------------------


class TestMatchesJobFilter:
    def test_exact_match(self):
        assert matches_job_filter("autofix-rfe", ["autofix-rfe"], []) is True

    def test_exact_no_match(self):
        assert matches_job_filter("other-job", ["autofix-rfe"], []) is False

    def test_glob_match(self):
        assert matches_job_filter("iterate-123", [], ["iterate-*"]) is True

    def test_glob_no_match(self):
        assert matches_job_filter("triage-456", [], ["iterate-*"]) is False

    def test_glob_multiple_patterns(self):
        patterns = ["iterate-*", "triage-*"]
        assert matches_job_filter("iterate-123", [], patterns) is True
        assert matches_job_filter("triage-456", [], patterns) is True
        assert matches_job_filter("build-789", [], patterns) is False

    def test_exact_takes_precedence(self):
        """Exact match should succeed even if no patterns match."""
        assert matches_job_filter("special", ["special"], ["other-*"]) is True

    def test_empty_filters_no_match(self):
        assert matches_job_filter("anything", [], []) is False

    def test_glob_star_matches_all(self):
        assert matches_job_filter("anything", [], ["*"]) is True

    def test_question_mark_glob(self):
        assert matches_job_filter("job-A", [], ["job-?"]) is True
        assert matches_job_filter("job-AB", [], ["job-?"]) is False
