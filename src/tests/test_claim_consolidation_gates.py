import json
import subprocess
import sys
from pathlib import Path


def _run_gate_check(root: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check-claim-consolidation-gates.py"), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_gate_check_rejects_zero_prediction_baseline(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "audit-claim-consolidation.py"),
            "--dataset",
            str(root / "data" / "semantic-claim-equivalence-v1.json"),
            "--threshold",
            "0.20",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report_path = tmp_path / "audit.json"
    report_path.write_text(audit.stdout)

    result = _run_gate_check(root, "--evaluation-report", str(report_path))

    assert result["automatic_assignment"]["authorized"] is False
    assert "no automatic equivalent predictions were evaluated" in result[
        "automatic_assignment"
    ]["reasons"]
    assert "automatic-equivalence precision is not measured" in result[
        "automatic_assignment"
    ]["reasons"]


def test_gate_check_accepts_passing_evaluation_and_reuse_simulation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(json.dumps({
        "evaluation_run_id": "passing-eval",
        "labeled_dataset_revision": "representative-v1",
        "equivalent_prediction_count": 100,
        "precision": 0.995,
        "false_merge_rate": 0.005,
    }))
    reuse_path = tmp_path / "reuse.json"
    reuse_path.write_text(json.dumps({
        "reuse_enabled": False,
        "simulation": {
            "simulated_reused_run_count": 8,
            "simulated_disagreeing_reuse_count": 0,
            "agreement_rate": 1.0,
            "estimated_saved_tokens": 1200,
        },
    }))

    result = _run_gate_check(
        root,
        "--evaluation-report",
        str(evaluation_path),
        "--reuse-report",
        str(reuse_path),
    )

    assert result["automatic_assignment"]["authorized"] is True
    assert result["verification_reuse"]["authorized"] is True


def test_gate_check_accepts_api_evaluation_list_shape(tmp_path):
    root = Path(__file__).resolve().parents[2]
    evaluation_path = tmp_path / "evaluations.json"
    evaluation_path.write_text(json.dumps({"evaluations": [{
        "evaluation_run_id": "latest-eval",
        "labeled_dataset_revision": "representative-v1",
        "equivalent_prediction_count": 25,
        "precision": 1.0,
        "false_merge_rate": 0.0,
    }]}))

    result = _run_gate_check(root, "--evaluation-report", str(evaluation_path))

    assert result["automatic_assignment"]["authorized"] is True
    assert result["automatic_assignment"]["evaluation_run_id"] == "latest-eval"


def test_gate_check_accepts_checked_in_synthetic_evidence():
    root = Path(__file__).resolve().parents[2]

    result = _run_gate_check(
        root,
        "--evaluation-report",
        str(root / "data" / "semantic-claim-consolidation-synthetic-evaluation.json"),
        "--reuse-report",
        str(root / "data" / "semantic-claim-consolidation-synthetic-reuse-report.json"),
    )

    assert result["automatic_assignment"]["authorized"] is True
    assert result["verification_reuse"]["authorized"] is True
