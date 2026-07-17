import json
import subprocess
import sys
from pathlib import Path


def test_dataset_audit_emits_recordable_non_authorizing_evaluation():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "audit-claim-consolidation.py"),
            "--dataset",
            str(root / "data" / "semantic-claim-equivalence-v1.json"),
            "--threshold",
            "0.20",
            "--evaluation-run-id",
            "test-eval-run",
            "--retrieval-revision",
            "token-overlap-test",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    record = report["evaluation_record"]

    assert report["candidate_retrieval_recall"] == 1.0
    assert report["automatic_equivalent_predictions"] == 0
    assert report["automatic_equivalence_precision"] is None
    assert record["evaluation_run_id"] == "test-eval-run"
    assert record["retrieval_revision"] == "token-overlap-test"
    assert record["equivalent_prediction_count"] == 0
    assert record["true_positive_count"] == 0
    assert record["false_positive_count"] == 0
    assert record["false_negative_count"] == 5
    assert record["precision"] is None
    assert record["recall"] == 0
    assert "not automatic authorization" in record["notes"]
