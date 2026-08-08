"""V2 澄清闭环（阶段 2 + 阶段 9 增强）：追问状态机、按步评估、中途缓解与更新语义。"""

from __future__ import annotations

from app.services.clarification import (
    MID_RELIEF,
    MID_RELIEF_QUESTION,
    QUESTION_FLOW,
    RELIEF_QUESTION,
    apply_answer,
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


def test_questionnaire_progresses_with_mid_relief_checkpoint():
    state = new_state("s1", "胸闷")
    assert next_prompt(state) == QUESTION_FLOW[0][1]

    # nature → 继续问 location
    assert apply_answer(state, "阵发性") == QUESTION_FLOW[1][1]
    assert state.step_index == 1
    assert state.answers["nature"] == "阵发性"

    # location → 插入中途缓解确认
    assert apply_answer(state, "胸口") == MID_RELIEF
    assert state.mid_relief_asked is True
    assert state.step_index == 2

    # duration / associated / risk_factors
    assert apply_answer(state, "两天") == QUESTION_FLOW[3][1]
    assert apply_answer(state, "有点恶心") == QUESTION_FLOW[4][1]
    assert apply_answer(state, "熬夜多") is None
    assert state.completed_questionnaire() is True
    assert next_prompt(state) == RELIEF_QUESTION


def test_update_semantics_records_overwrite_for_key_fields():
    state = new_state("s1", "头疼")
    state.step_index = 1  # location 节点
    state.answers["location"] = "右侧"
    apply_answer(state, "两侧")
    assert state.answers["location"] == "两侧"
    assert any("location" in update and "→" in update for update in state.updates)


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
    state.answers["nature"] = "阵发性"
    store.set(state)

    loaded = store.get("store-test")
    assert loaded is not None
    assert loaded.session_id == "store-test"
    assert loaded.answers == {"nature": "阵发性"}

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


def test_pipeline_clarify_starts_and_advances():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-flow-1")

    first = namespace["run_agent_tool_query"]("我最近总是胸闷，怎么回事？", session_id="clr-flow-1")
    assert first["clarification_required"] is True
    assert first["clarification_completed"] is False
    assert "症状" in first["answer"]
    assert first["next_action"] == "continue_supplement"

    second = namespace["run_agent_tool_query"]("阵发性的", session_id="clr-flow-1")
    assert second["clarification_required"] is True
    assert "部位" in second["answer"]

    store.clear("clr-flow-1")


def test_pipeline_mid_relief_inserted_after_location():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-mid")

    namespace["run_agent_tool_query"]("我最近总是头晕", session_id="clr-mid")
    namespace["run_agent_tool_query"]("一阵一阵的", session_id="clr-mid")
    third = namespace["run_agent_tool_query"]("后脑勺", session_id="clr-mid")

    assert third["answer"] == MID_RELIEF_QUESTION
    assert third["clarification_step"] == 2
    store.clear("clr-mid")


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
    namespace["run_agent_tool_query"]("阵发性", session_id="clr-cleared")
    namespace["run_agent_tool_query"]("太阳穴", session_id="clr-cleared")
    result = namespace["run_agent_tool_query"]("现在已经不疼了", session_id="clr-cleared")

    assert result["clarification_upgraded"] is False
    assert result["clarification_completed"] is True
    assert store.get("clr-cleared") is None


def test_pipeline_clarify_upgrades_when_not_relieved():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-flow-2")

    namespace["run_agent_tool_query"]("最近总是头晕，不知道什么原因", session_id="clr-flow-2")
    answers = [
        "一阵一阵的",
        "后脑勺",
        "两天了，反复出现",
        "有点恶心",
        "最近熬夜比较多",
        "没有其他诱因",
    ]
    result = None
    for answer in answers:
        result = namespace["run_agent_tool_query"](answer, session_id="clr-flow-2")
        assert result["clarification_required"] is True

    # 问卷完成 → 最终缓解确认
    assert result["answer"] == RELIEF_QUESTION

    upgraded = namespace["run_agent_tool_query"]("没有缓解，更严重了", session_id="clr-flow-2")
    assert upgraded["clarification_upgraded"] is True
    assert upgraded["clarification_completed"] is True
    assert upgraded["risk_level"] == "urgent"
    assert upgraded["next_action"] == "contact_doctor"
    assert store.get("clr-flow-2") is None


def test_pipeline_relieved_ends_without_upgrade():
    namespace = _install()
    store = get_clarification_store()
    store.clear("clr-flow-3")

    namespace["run_agent_tool_query"]("最近有点不舒服，总想吐", session_id="clr-flow-3")
    for answer in ["一阵一阵的", "胃部", "半天", "没有其他症状", "没有诱因", "最近正常"]:
        namespace["run_agent_tool_query"](answer, session_id="clr-flow-3")

    relieved = namespace["run_agent_tool_query"]("已经缓解了", session_id="clr-flow-3")
    assert relieved["clarification_upgraded"] is False
    assert relieved["clarification_completed"] is True
    assert relieved["next_action"] == "continue_supplement"
    assert store.get("clr-flow-3") is None


def test_pipeline_non_vague_question_skips_clarify():
    namespace = _install()
    result = namespace["run_agent_tool_query"]("总结我的情况", session_id="clr-skip")
    nodes = [item["node"] for item in result["agent_trajectory"]]
    assert "clarify" not in nodes
    assert result.get("clarification_required") is not True