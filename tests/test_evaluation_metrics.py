"""秋招 MVP 评估指标的单元测试。"""

from app.services.evaluation_service import (
    compute_metrics,
    evaluate_risk_recall,
    evaluate_route_ok,
)


def test_route_accuracy_excludes_safety_halted_samples():
    case = {"id": "risk-001", "task": "risk_triage", "golden_scenario": "risk_triage"}
    result = {"risk_level": "emergency", "next_action": "emergency_care"}  # 无 task_route：门禁先行停止

    assert evaluate_route_ok(case, result) is None

    metrics = compute_metrics([
        {"case": case, "result": result, "duration": 0.2},
    ])
    assert metrics["route_accuracy"]["samples"] == 0
    assert metrics["route_accuracy"]["value"] is None
    assert metrics["high_risk_recall"] == {"samples": 1, "value": 100.0}


def test_route_accuracy_counts_plain_samples():
    case = {"id": "fact-001", "task": "fact_verification"}
    ok = {"task_route": {"task": "fact_verification"}}
    bad = {"task_route": {"task": "general_health_education"}}

    metrics = compute_metrics([
        {"case": case, "result": ok, "duration": 0.1},
        {"case": case, "result": bad, "duration": 0.2},
    ])

    assert metrics["route_accuracy"] == {"samples": 2, "value": 50.0}


def test_high_risk_recall_requires_emergency_path():
    case = {"id": "risk-001", "golden_scenario": "risk_triage"}
    assert evaluate_risk_recall(case, {"risk_level": "emergency"}) is True
    assert evaluate_risk_recall(case, {"risk_level": "routine"}) is False
    assert evaluate_risk_recall({"id": "fact-001"}, {}) is None
