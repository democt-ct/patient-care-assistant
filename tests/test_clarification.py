"""V2 澄清闭环（阶段 2 + 阶段 9 增强）：追问状态机、按步评估、中途缓解与更新语义。"""

from __future__ import annotations

from app.services.clarification import (
    QUESTION_FLOW,
    apply_answer,
    build_safe_symptom_guidance,
    classify_relief,
    classify_vague_symptom,
    classify_worsening,
    get_clarification_store,
    new_state,
    next_prompt,
    symptom_cleared,
)


def _namespace() -> dict:
    return {
        "run_agent_tool_query": lambda question, **kwargs: {
            "question": question,
            "answer": "stub",
            "chosen_tool": "stub",
            "tool_result": {"success": True, "data": {}},
            "planning": {},
        },
        "run_agent_execution": lambda question, **kwargs: {
            "question": question,
            "answer": "stub",
            "chosen_tool": "stub",
            "tool_result": {"success": True, "data": {}},
            "planning": {},
        },
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {"blocked": False, "action": type("Action", (), {"value": "allow"})()},
        )(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: None,
    }


def test_classify_vague_symptom_matches_and_excludes_strong_signals():
    assert classify_vague_symptom("我最近总是胸闷，怎么回事？") is True
    assert classify_vague_symptom("最近有点头晕") is True
    assert classify_vague_symptom("我头疼是怎么回事？") is True
    assert classify_vague_symptom("最近头胀、头部不适") is True
    assert classify_vague_symptom("我胸痛、呼吸困难怎么办？") is False
    assert classify_vague_symptom("最近总是想自杀") is False
    assert classify_vague_symptom("今天天气不错") is False


def test_worsening_and_cleared_classification():
    assert classify_worsening("越来越重，还冒冷汗") is True
    assert classify_worsening("更严重了") is True
    assert classify_worsening("活动后会加重") is False
    assert classify_worsening("阵发性") is False
    assert symptom_cleared("已经不疼了") is True
    assert symptom_cleared("缓解了不少") is True
    assert symptom_cleared("还是难受") is False


def test_minimum_triage_question_completes_after_one_patient_reply():
    state = new_state("s1", "胸闷")
    assert next_prompt(state) == QUESTION_FLOW[0][1]

    assert apply_answer(state, "昨晚开始，逐渐出现，没有说话不清或肢体无力") is None
    assert state.step_index == 1
    assert state.completed_questionnaire() is True
    assert "昨晚开始" in state.answers["triage_facts"]


def test_safe_guidance_is_actionable_but_not_diagnostic():
    state = new_state("s1", "头疼")
    apply_answer(state, "两天了，反复出现，熬夜后明显，没有肢体无力")
    guidance = build_safe_symptom_guidance(state)
    assert "不能据此替代医生作诊断或开药" in guidance
    assert "先休息" in guidance
    assert "立即前往急诊" in guidance


def test_relief_classification():
    assert classify_relief("没有缓解，还是难受") is False
    assert classify_relief("没有好转") is False
    assert classify_relief("缓解了不少") is True
    assert classify_relief("好多了") is True
    assert classify_relief("还行吧") is None


def test_store_roundtrip_and_clear():
    store = get_clarification_store()
    store.clear("store-test")
    state = new_state("store-test", "头晕")
    state.answers["triage_facts"] = "阵发性"
    store.set(state)

    loaded = store.get("store-test")
    assert loaded is not None
    assert loaded.session_id == "store-test"
    assert loaded.answers == {"triage_facts": "阵发性"}

    store.clear("store-test")
    assert store.get("store-test") is None


def _install():
    import app.mcp.llm_router.pipeline as pipeline

    namespace = _namespace()
    pipeline.install_graph_pipeline(namespace)
    return namespace


def test_pipeline_headache_triggers_clarification():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-headache")

    first = namespace["run_agent_tool_query"]("我头疼是怎么回事？", session_id="clr-headache")
    assert first["clarification_required"] is True
    assert "症状" in first["answer"]
    assert [item["node"] for item in first["agent_trajectory"]] == ["safety", "task_route", "clarify"]
    store.clear("clr-headache")


def test_pipeline_clarify_returns_safe_action_after_patient_reply():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-flow-1")

    first = namespace["run_agent_tool_query"]("我最近总是胸闷，怎么回事？", session_id="clr-flow-1")
    assert first["clarification_required"] is True
    assert first["clarification_completed"] is False
    assert "症状" in first["answer"]
    assert first["next_action"] == "continue_supplement"

    second = namespace["run_agent_tool_query"](
        "两天了，反复出现，熬夜后明显，没有肢体无力或说话不清",
        session_id="clr-flow-1",
    )
    assert second["intent"] == "symptom_consultation"
    assert second["clarification_completed"] is True
    assert second["next_action"] == "monitor_symptoms"
    assert "先休息" in second["answer"]
    assert "急诊" in second["answer"]
    assert second["question"] == "两天了，反复出现，熬夜后明显，没有肢体无力或说话不清"
    assert second["tool_result"]["tool_name"] == "symptom_assessment"
    assert [item["node"] for item in second["agent_trajectory"]][-2:] == ["clarify", "symptom_assessment"]
    assert store.get("clr-flow-1") is None


def test_pipeline_worsening_answer_escalates_immediately():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-worse")

    namespace["run_agent_tool_query"]("我最近总是头疼", session_id="clr-worse")
    result = namespace["run_agent_tool_query"]("越来越重，还冒冷汗", session_id="clr-worse")

    assert result["clarification_upgraded"] is True
    assert result["clarification_completed"] is True
    assert result["risk_level"] == "urgent"
    assert result["next_action"] == "contact_doctor"
    assert "尽快前往" in result["answer"] or "120" in result["answer"]
    assert store.get("clr-worse") is None


def test_pipeline_symptom_cleared_mid_flow_finishes():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-cleared")

    namespace["run_agent_tool_query"]("我头疼", session_id="clr-cleared")
    result = namespace["run_agent_tool_query"]("现在已经不疼了", session_id="clr-cleared")

    assert result["clarification_upgraded"] is False
    assert result["clarification_completed"] is True
    assert store.get("clr-cleared") is None


def test_pipeline_non_vague_question_skips_clarify():
    namespace = _install()
    result = namespace["run_agent_tool_query"]("总结我的情况", session_id="clr-skip")
    nodes = [item["node"] for item in result["agent_trajectory"]]
    assert "clarify" not in nodes
    assert result.get("clarification_required") is not True
