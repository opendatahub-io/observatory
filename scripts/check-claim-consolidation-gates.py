#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _fetch_json(base_url: str, path: str, token: str | None) -> dict:
    request = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")))
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _evaluation_record(report: dict) -> dict | None:
    if "evaluation_record" in report:
        return report["evaluation_record"]
    if "evaluation_run_id" in report:
        return report
    if "evaluations" in report and report["evaluations"]:
        return report["evaluations"][0]
    return None


def evaluate_automatic_gate(
    report: dict,
    *,
    minimum_precision: float,
    maximum_false_merge_rate: float,
) -> dict:
    record = _evaluation_record(report)
    reasons = []
    if record is None:
        reasons.append("missing evaluation_record")
        return {"authorized": False, "reasons": reasons}
    prediction_count = record.get("equivalent_prediction_count") or 0
    precision = record.get("precision")
    false_merge_rate = record.get("false_merge_rate")
    if prediction_count <= 0:
        reasons.append("no automatic equivalent predictions were evaluated")
    if precision is None:
        reasons.append("automatic-equivalence precision is not measured")
    elif precision < minimum_precision:
        reasons.append(
            f"precision {precision:.6f} is below required {minimum_precision:.6f}"
        )
    if false_merge_rate is None:
        reasons.append("false-merge rate is not measured")
    elif false_merge_rate > maximum_false_merge_rate:
        reasons.append(
            "false-merge rate "
            f"{false_merge_rate:.6f} exceeds allowed {maximum_false_merge_rate:.6f}"
        )
    return {
        "authorized": not reasons,
        "reasons": reasons,
        "evaluation_run_id": record.get("evaluation_run_id"),
        "labeled_dataset_revision": record.get("labeled_dataset_revision"),
        "precision": precision,
        "false_merge_rate": false_merge_rate,
        "equivalent_prediction_count": prediction_count,
    }


def evaluate_reuse_gate(
    report: dict,
    *,
    minimum_agreement_rate: float,
    minimum_saved_tokens: int,
    require_zero_disagreements: bool,
) -> dict:
    simulation = report.get("simulation") or {}
    reasons = []
    agreement_rate = simulation.get("agreement_rate")
    simulated_count = simulation.get("simulated_reused_run_count") or 0
    disagreeing_count = simulation.get("simulated_disagreeing_reuse_count") or 0
    saved_tokens = simulation.get("estimated_saved_tokens") or 0
    if report.get("reuse_enabled"):
        reasons.append("reuse is already enabled; expected simulation-only evidence")
    if simulated_count <= 0:
        reasons.append("no simulated reused verification runs were measured")
    if agreement_rate is None:
        reasons.append("reuse agreement rate is not measured")
    elif agreement_rate < minimum_agreement_rate:
        reasons.append(
            f"agreement rate {agreement_rate:.6f} is below required {minimum_agreement_rate:.6f}"
        )
    if require_zero_disagreements and disagreeing_count > 0:
        reasons.append(f"{disagreeing_count} simulated reuse disagreements were found")
    if saved_tokens < minimum_saved_tokens:
        reasons.append(
            f"estimated saved tokens {saved_tokens} is below required {minimum_saved_tokens}"
        )
    return {
        "authorized": not reasons,
        "reasons": reasons,
        "simulated_reused_run_count": simulated_count,
        "simulated_disagreeing_reuse_count": disagreeing_count,
        "agreement_rate": agreement_rate,
        "estimated_saved_tokens": saved_tokens,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check semantic claim consolidation authorization gates."
    )
    parser.add_argument("--evaluation-report", type=Path)
    parser.add_argument("--reuse-report", type=Path)
    parser.add_argument(
        "--api-base-url",
        help="Fetch latest evaluation and reuse simulation from a running Observatory API.",
    )
    parser.add_argument(
        "--api-token",
        help="Optional bearer token for --api-base-url requests.",
    )
    parser.add_argument("--minimum-precision", type=float, default=0.99)
    parser.add_argument("--maximum-false-merge-rate", type=float, default=0.01)
    parser.add_argument("--minimum-reuse-agreement", type=float, default=1.0)
    parser.add_argument("--minimum-saved-tokens", type=int, default=1)
    parser.add_argument("--allow-reuse-disagreements", action="store_true")
    args = parser.parse_args()
    if not args.evaluation_report and not args.reuse_report and not args.api_base_url:
        parser.error("provide --evaluation-report, --reuse-report, --api-base-url, or a combination")

    result = {}
    evaluation_report = None
    reuse_report = None
    if args.evaluation_report:
        evaluation_report = _load_json(args.evaluation_report)
    elif args.api_base_url:
        evaluation_report = _fetch_json(
            args.api_base_url, "/api/v2/claim-consolidation/evaluations?limit=1", args.api_token
        )
    if args.reuse_report:
        reuse_report = _load_json(args.reuse_report)
    elif args.api_base_url:
        reuse_report = _fetch_json(
            args.api_base_url,
            "/api/v2/claim-consolidation/verification-reuse-opportunities",
            args.api_token,
        )

    if evaluation_report:
        result["automatic_assignment"] = evaluate_automatic_gate(
            evaluation_report,
            minimum_precision=args.minimum_precision,
            maximum_false_merge_rate=args.maximum_false_merge_rate,
        )
    if reuse_report:
        result["verification_reuse"] = evaluate_reuse_gate(
            reuse_report,
            minimum_agreement_rate=args.minimum_reuse_agreement,
            minimum_saved_tokens=args.minimum_saved_tokens,
            require_zero_disagreements=not args.allow_reuse_disagreements,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
