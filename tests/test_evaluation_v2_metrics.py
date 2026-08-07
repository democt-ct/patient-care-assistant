"""V2 评估指标：智能证据判定抽样、澄清完成率、不必要追问率。"""

from __future__ import annotations

from app.services.evaluation_service import (
    compute_metrics,
    evaluate_clarification_completion,
    evaluate_judge_accuracy,
    evaluate_unnecessary_clarification,
)


def _result(**overrides) -> dict:
    base = {
        "answer": "ok",
        "intent": "general_medical_question",
        "evidence_check": {"status": "sufficient"},
        "task_route": {"task": "general_health_education"},
    }
    base.update(overrides)
    return base


def test_judge_accuracy_matches_when_present():
    case = {"expected_judge": "supported"}
    result = _result(evidence_check={"status": "sufficient", "judge": {"verdict": "supported"}})
    assert evaluate_judge_accuracy(case, result) is True


def test_judge_accuracy_fails_on_mismatch():
    case = {"expected_judge": "supported"}
    result = _result(evidence_check={"status": "sufficient", "judge": {"verdict": "conflict"}})
    assert evaluate_judge_accuracy(case, result) is False


def test_judge_accuracy_skipped_without_judge():
    assert evaluate_judge_accuracy({"expected_judge": "supported"}, _result()) is None
    assert evaluate_judge_accuracy({}, _result()) is None


def test_clarification_completion_metric():
    case = {"expected_clarification": True}
    assert evaluate_clarification_completion(case, _result(clarification_required=True)) is True
    assert evaluate_clarification_completion(case, _result()) is False
    assert evaluate_clarification_completion({}, _result()) is None


def test_unnecessary_clarification_metric():
    case = {}
    assert evaluate_unnecessary_clarification(case, _result()) is True
    assert evaluate_unnecessary_clarification(case, _result(clarification_required=True)) is False
    assert evaluate_unnecessary_clarification({"expected_clarification": True}, _result()) is None


def test_compute_metrics_keeps_existing_mvp_keys():
    metrics = compute_metrics(
        [
            {
                "case": {"expected_judge": "supported", "expected_clarification": True},
                "result": _result(
                    evidence_check={"status": "sufficient", "judge": {"verdict": "supported"}},
                    clarification_required=True,
                ),
                "duration": 1.2,
            },
            {
                "case": {},
                "result": _result(),
                "duration": 0.8,
            },
        ]
    )
    for key in (
        "route_accuracy",
        "high_risk_recall",
        "danger_interception_rate",
        "citation_correctness",
        "conflict_detection_rate",
        "refusal_correct_rate",
        "unnecessary_refusal_rate",
        "p95_latency_seconds",
    ):
        assert key in metrics, f"missing existing MVP metric: {key}"
    assert metrics["judge_accuracy"]["samples"] == 1
    assert metrics["judge_accuracy"]["value"] == 100.0
    assert metrics["clarification_completion_rate"]["samples"] == 1
    assert metrics["clarification_completion_rate"]["value"] == 100.0
    assert metrics["unnecessary_clarification_rate"]["samples"] == 1
    assert metrics["unnecessary_clarification_rate"]["value"] == 100.0
