from app.config.evaluation_cases import EVALUATION_CASES
from app.models.audit_log import EvaluationRun
from app.services.evaluation_service import (
    persist_evaluation_run,
    score_case,
    serialize_evaluation_run,
    summarize_evaluation_runs,
)


def _fully_correct_answer(case):
    return " ".join(case.get("expected_keywords") or [])


def test_server_evaluation_score_matches_its_documented_contract():
    case = EVALUATION_CASES[0]
    result = score_case(
        case,
        answer=_fully_correct_answer(case),
        intent=case["expected_intents"][0],
    )

    assert result["passed"] is True
    assert result["scores"]["total"] == 100.0
    assert result["missing_keywords"] == []
    assert result["scoring_version"] == "v2"


def test_safe_medical_warnings_are_not_counted_as_safety_violations():
    cases = {case["id"]: case for case in EVALUATION_CASES}
    examples = (
        ("symptom-001", "建议低盐饮食、监测血压并规律服药，不要自行停药。", "symptom_consultation"),
        ("symptom-002", "请监测体温，必要时在医生指导下使用布洛芬；孩子头孢过敏，应避免使用头孢。", "symptom_consultation"),
        ("allergy-001", "你有磺胺过敏史，不能使用磺胺类抗生素。", "symptom_consultation"),
    )

    for case_id, answer, intent in examples:
        result = score_case(cases[case_id], answer=answer, intent=intent)
        assert result["scores"]["safety"] == 100.0
        assert result["found_forbidden"] == []
        assert result["missing_safety_requirements"] == []


def test_unsafe_medical_recommendation_is_still_rejected():
    case = next(case for case in EVALUATION_CASES if case["id"] == "allergy-001")
    result = score_case(case, answer="你对磺胺过敏，但可以使用磺胺类抗生素。", intent="symptom_consultation")

    assert result["scores"]["safety"] == 0.0
    assert result["found_forbidden"] == ["可以使用磺胺"]


def test_persisted_evaluation_excludes_raw_answer_and_is_summarized(db_session):
    case = EVALUATION_CASES[0]
    answer = _fully_correct_answer(case)
    record = persist_evaluation_run(
        db_session,
        case=case,
        answer=answer,
        intent=case["expected_intents"][0],
        run_id="test-evaluation-run",
        trace_id="trace-for-test",
    )

    stored = serialize_evaluation_run(record)
    assert stored["passed"] is True
    assert "answer" not in stored["result"]
    assert stored["result"]["answer_length"] == len(answer)
    assert db_session.query(EvaluationRun).count() == 1

    summary = summarize_evaluation_runs([record])
    assert summary["pass_rate"] == 100.0
    assert summary["cases"][case["id"]]["average_score"] == 100.0
