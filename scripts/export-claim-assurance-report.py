#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


FILTER_ARGS = (
    "jira_key", "claim_occurrence_id", "normalized_claim_id", "canonical_group_id",
    "artifact_type", "pipeline_slug", "source_file", "claim_type", "verdict",
    "processing_state", "explanation_category", "improvement_target",
    "human_review_required", "created_after", "created_before",
)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    Path(temp_name).replace(path)


def _fetch(base_url: str, suffix: str, params: dict[str, object]) -> bytes:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{base_url.rstrip('/')}/api/v2/claims/reports/{suffix}?{query}"
    try:
        with urlopen(url, timeout=60) as response:  # noqa: S310
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"export request failed: HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise SystemExit(f"export request failed: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Claim Assurance reports")
    parser.add_argument("--api-base-url", default=os.environ.get("OBSERVATORY_URL"))
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="both")
    parser.add_argument("--output", required=True)
    parser.add_argument("--all", action="store_true", help="Allow an unfiltered export")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--jira-key")
    parser.add_argument("--claim-occurrence-id", type=int)
    parser.add_argument("--normalized-claim-id", type=int)
    parser.add_argument("--canonical-group-id", type=int)
    parser.add_argument("--artifact-type")
    parser.add_argument("--pipeline-slug")
    parser.add_argument("--source-file")
    parser.add_argument("--claim-type")
    parser.add_argument("--verdict")
    parser.add_argument("--processing-state")
    parser.add_argument("--explanation-category")
    parser.add_argument("--improvement-target")
    parser.add_argument("--human-review-required", choices=("true", "false"))
    parser.add_argument("--created-after")
    parser.add_argument("--created-before")
    args = parser.parse_args()

    if not args.api_base_url:
        raise SystemExit("--api-base-url or OBSERVATORY_URL is required")
    params = {name: getattr(args, name) for name in FILTER_ARGS}
    if args.human_review_required is not None:
        params["human_review_required"] = args.human_review_required
    params["observatory_url"] = args.api_base_url
    params["limit"] = args.limit
    scoped = any(params.get(name) not in (None, "") for name in FILTER_ARGS)
    if not scoped and not args.all:
        raise SystemExit("provide at least one scope filter or pass --all")

    output = Path(args.output)
    written = []
    json_content = _fetch(args.api_base_url, "export.json", params)
    summary = json.loads(json_content).get("summary", {})
    print(
        "matching_occurrences="
        f"{summary.get('matching_occurrences', 'unknown')} "
        "exported_occurrences="
        f"{summary.get('exported_occurrences', 'unknown')}"
    )
    if args.format in {"json", "both"}:
        path = output if args.format == "json" and output.suffix else output.with_suffix(".json")
        _atomic_write(path, json_content)
        written.append(path)
    if args.format in {"markdown", "both"}:
        suffix = "export.md"
        path = output if args.format == "markdown" and output.suffix else output.with_suffix(".md")
        _atomic_write(path, _fetch(args.api_base_url, suffix, params))
        written.append(path)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
