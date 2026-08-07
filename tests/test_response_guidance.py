"""V2 阶段 4/5：普通风险内嵌升级指引与引用安全网行为测试。"""

from __future__ import annotations

from app.services.response_guidance import embed_escalation_guidance


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
            "answer": "可以先用温水热敷缓解，并注意休息。",
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


def test_embeds_guidance_for_pain_question():
    answer, risk = embed_escalation_guidance("可以先用温水热敷缓解。", "疼痛一般如何缓解？")
    assert risk == "urgent"
    assert "120" in answer
    assert "急诊" in answer


def test_no_embedding_for_plain_question():
    answer, risk = embed_escalation_guidance("注意休息。", "高血压日常注意什么？")
    assert risk == "routine"
    assert answer == "注意休息。"


def test_embedding_is_idempotent():
    first, _ = embed_escalation_guidance("注意。", "有点疼痛")
    second, _ = embed_escalation_guidance(first, "有点疼痛")
    assert first == second


def test_pipeline_embeds_guidance_in_output():
    import app.mcp.llm_router.pipeline as pipeline

    namespace = _namespace()
    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("疼痛一般如何缓解？")

    assert result["risk_level"] == "urgent"
    assert "120" in result["answer"]
    assert "急诊" in result["answer"]
