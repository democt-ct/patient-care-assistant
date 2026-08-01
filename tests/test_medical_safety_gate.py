from app.mcp.medical_safety_gate import (
    SafetyGateAction,
    evaluate_medical_safety,
    format_safety_gate_response,
)
from app.mcp.llm_router import run_agent_tool_query, run_agent_tool_query_stream


def test_emergency_question_is_blocked_before_generation():
    decision = evaluate_medical_safety("我现在胸痛，还呼吸困难")

    assert decision.action == SafetyGateAction.EMERGENCY
    assert "120" in format_safety_gate_response(decision)


def test_medication_change_is_not_sent_to_free_form_generation():
    decision = evaluate_medical_safety("我的降压药可以自己停药吗？")

    assert decision.action == SafetyGateAction.CLINICIAN_REVIEW
    assert "不能据此给出具体调整方案" in format_safety_gate_response(decision)


def test_dose_and_interaction_questions_require_clinician_review():
    assert evaluate_medical_safety("这个药一次吃多少毫克？").blocked
    assert evaluate_medical_safety("阿司匹林和布洛芬可以一起吃吗？").blocked


def test_general_education_question_is_allowed():
    decision = evaluate_medical_safety("高血压日常生活中应注意什么？")

    assert decision.action == SafetyGateAction.ALLOW


def test_router_returns_gate_response_without_initializing_the_model(monkeypatch):
    def fail_if_called():
        raise AssertionError("The LLM must not be initialized for a blocked request")

    monkeypatch.setattr("app.mcp.llm_router.get_llm", fail_if_called)

    result = run_agent_tool_query("华法林和布洛芬能一起吃吗？")

    assert result["chosen_tool"] == "medical_safety_gate"
    assert result["planning_strategy"] == "pre_generation_safety_gate"


def test_streaming_router_applies_the_same_gate(monkeypatch):
    monkeypatch.setattr(
        "app.mcp.llm_router.get_llm",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not be initialized")),
    )

    result = run_agent_tool_query_stream("我胸痛得厉害，呼吸困难")

    assert result["chosen_tool"] == "medical_safety_gate"
