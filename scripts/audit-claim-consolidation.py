#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[^\W_]{2,}", re.UNICODE)
STOP_WORDS = {
    "and", "are", "for", "from", "has", "have", "into", "not", "that",
    "the", "their", "this", "was", "were", "will", "with",
}


def tokens(text: str, aliases: dict[str, str]) -> set[str]:
    normalized = text.casefold()
    for alias, canonical in aliases.items():
        normalized = normalized.replace(alias.casefold(), canonical.casefold())
    return {
        token for token in TOKEN_PATTERN.findall(normalized)
        if token not in STOP_WORDS
    }


def similarity(left: str, right: str, aliases: dict[str, str]) -> float:
    left_tokens = tokens(left, aliases)
    right_tokens = tokens(right, aliases)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0


def audit_dataset(
    path: Path,
    threshold: float,
    evaluation_run_id: str,
    retrieval_revision: str | None,
    decision_revision: str,
) -> dict:
    dataset = json.loads(path.read_text())
    aliases = dataset.get("alias_map", {})
    cases = dataset["cases"]
    rows = []
    for case in cases:
        score = similarity(case["left"], case["right"], aliases)
        rows.append({"id": case["id"], "label": case["label"], "score": score,
                     "retrieved": score >= threshold})
    duplicate_cases = [row for row in rows if row["label"] == "equivalent"]
    retrieved_duplicates = [row for row in duplicate_cases if row["retrieved"]]
    equivalent_predictions = []
    true_positive_count = sum(
        row["label"] == "equivalent" for row in equivalent_predictions
    )
    false_positive_count = sum(
        row["label"] != "equivalent" for row in equivalent_predictions
    )
    false_negative_count = len(duplicate_cases) - true_positive_count
    equivalent_prediction_count = len(equivalent_predictions)
    precision = (
        true_positive_count / equivalent_prediction_count
        if equivalent_prediction_count else None
    )
    recall = (
        true_positive_count / len(duplicate_cases) if duplicate_cases else None
    )
    false_merge_rate = (
        false_positive_count / equivalent_prediction_count
        if equivalent_prediction_count else None
    )
    candidate_volume = sum(row["retrieved"] for row in rows)
    label_counts = dict(Counter(row["label"] for row in rows))
    resolved_retrieval_revision = (
        retrieval_revision or f"token-overlap-threshold-{threshold:.2f}"
    )
    evaluation_record = {
        "evaluation_run_id": evaluation_run_id,
        "labeled_dataset_revision": dataset["revision"],
        "retrieval_revision": resolved_retrieval_revision,
        "decision_revision": decision_revision,
        "candidate_count": candidate_volume,
        "labeled_pair_count": len(rows),
        "equivalent_prediction_count": equivalent_prediction_count,
        "true_positive_count": true_positive_count,
        "false_positive_count": false_positive_count,
        "false_negative_count": false_negative_count,
        "precision": precision,
        "recall": recall,
        "false_merge_rate": false_merge_rate,
        "drift_summary": {
            "label_counts": label_counts,
            "threshold": threshold,
            "retrieval_revision": resolved_retrieval_revision,
        },
        "notes": (
            "Conservative baseline abstains from automatic equivalent predictions; "
            "record is suitable for audit history but not automatic authorization."
        ),
    }
    return {
        "dataset_revision": dataset["revision"],
        "labeled_pair_count": len(rows),
        "label_counts": label_counts,
        "candidate_volume": candidate_volume,
        "candidate_retrieval_recall": (
            len(retrieved_duplicates) / len(duplicate_cases) if duplicate_cases else None
        ),
        "automatic_equivalent_predictions": equivalent_prediction_count,
        "automatic_equivalence_precision": precision,
        "automatic_equivalence_recall": recall,
        "estimated_repeated_verification_pairs": len(duplicate_cases),
        "threshold": threshold,
        "evaluation_record": evaluation_record,
        "cases": rows,
    }


def audit_database(path: Path, threshold: float, limit: int) -> dict:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    claims = [dict(row) for row in connection.execute(
        "SELECT id, claim_text FROM claims ORDER BY id LIMIT ?", (limit,)
    )]
    occurrence_count = connection.execute(
        "SELECT COUNT(*) FROM claim_occurrences"
    ).fetchone()[0]
    pairs = []
    for index, left in enumerate(claims):
        for right in claims[index + 1:]:
            score = similarity(left["claim_text"], right["claim_text"], {})
            if score >= threshold:
                pairs.append({
                    "left_normalized_claim_id": left["id"],
                    "right_normalized_claim_id": right["id"],
                    "score": score,
                })
    connection.close()
    return {
        "read_only": True,
        "text_identity_count": len(claims),
        "occurrence_count": occurrence_count,
        "candidate_volume": len(pairs),
        "duplicate_group_rate": None,
        "estimated_repeated_verification_work": None,
        "note": "Candidate pairs require human labels before duplicate rates are known.",
        "candidates": pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only baseline audit for semantic claim consolidation"
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument(
        "--evaluation-run-id",
        default="semantic-claim-equivalence-v1-baseline",
        help="Evaluation run id to include in dataset audit output.",
    )
    parser.add_argument(
        "--retrieval-revision",
        help="Override retrieval revision recorded in the evaluation payload.",
    )
    parser.add_argument(
        "--decision-revision",
        default="conservative-abstain-v1",
        help="Decision revision recorded in the evaluation payload.",
    )
    args = parser.parse_args()
    if bool(args.database) == bool(args.dataset):
        parser.error("provide exactly one of --database or --dataset")
    try:
        report = (
            audit_database(args.database, args.threshold, args.limit)
            if args.database else audit_dataset(
                args.dataset,
                args.threshold,
                args.evaluation_run_id,
                args.retrieval_revision,
                args.decision_revision,
            )
        )
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"database audit unavailable: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
